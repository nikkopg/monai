import { redirect } from "next/navigation";

// The dashboard was renamed Overview; old /cashflow bookmarks land there.
export default function CashflowRedirect() {
  redirect("/overview");
}
