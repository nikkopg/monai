import { test, expect } from "@playwright/test";
import { checkBasic } from "../app/lib/basicAuth";
import { UI_PASSWORD } from "../playwright.config";

// Synthetic values only.
const PW = "pw-synthetic";
const API = "api-synthetic";
const APPR = "appr-synthetic";
const basic = (u: string, p: string) => "Basic " + btoa(`${u}:${p}`);

test.describe("helper", () => {
  test("right user and password is ok", async () => {
    expect(await checkBasic(basic("monai", PW), PW, API, APPR)).toBe("ok");
  });
  test("scheme is case-insensitive", async () => {
    expect(await checkBasic("basic " + btoa(`monai:${PW}`), PW, API, APPR)).toBe("ok");
  });
  test("wrong password, wrong user, missing or garbage header are unauthorized", async () => {
    expect(await checkBasic(basic("monai", "nope"), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic(basic("admin", PW), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic(null, PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("", PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Basic !!!", PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Basic " + btoa("nocolon"), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Bearer " + PW, PW, API, APPR)).toBe("unauthorized");
  });
  test("an unset password is locked whatever the header", async () => {
    expect(await checkBasic(basic("monai", ""), "", API, APPR)).toBe("locked");
    expect(await checkBasic(null, "", API, APPR)).toBe("locked");
  });
  test("a password equal to either key is locked even with matching credentials", async () => {
    expect(await checkBasic(basic("monai", API), API, API, APPR)).toBe("locked");
    expect(await checkBasic(basic("monai", APPR), APPR, API, APPR)).toBe("locked");
  });
  test("empty keys do not lock a set password", async () => {
    expect(await checkBasic(basic("monai", PW), PW, "", "")).toBe("ok");
  });
});

// Node fetch, not the `request`/`page` fixtures: those answer the challenge from
// the config credentials and would pass for the wrong reason. Never request /api
// with credentials here: the dev proxy defaults to the live backend on 8001.
test.describe("server", () => {
  test.setTimeout(60_000);
  const get = (baseURL: string | undefined, path: string, authz?: string) =>
    fetch(new URL(path, baseURL), { headers: authz ? { authorization: authz } : {}, redirect: "manual" });

  test("no credentials gets 401 with a Basic challenge", async ({ baseURL }) => {
    const r = await get(baseURL, "/");
    expect(r.status).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain('Basic realm="monai"');
  });
  test("wrong password and wrong username get 401", async ({ baseURL }) => {
    expect((await get(baseURL, "/", basic("monai", "nope"))).status).toBe(401);
    expect((await get(baseURL, "/", basic("admin", UI_PASSWORD))).status).toBe(401);
  });
  test("right credentials get the page", async ({ baseURL }) => {
    expect((await get(baseURL, "/chat", basic("monai", UI_PASSWORD))).status).toBe(200);
  });
  test("/api without credentials is 401 before the proxy runs", async ({ baseURL }) => {
    expect((await get(baseURL, "/api/accounts")).status).toBe(401);
  });
});
