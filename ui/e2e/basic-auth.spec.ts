import { test, expect } from "@playwright/test";
import { checkBasic } from "../app/lib/basicAuth";

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
