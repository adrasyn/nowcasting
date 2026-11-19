import { execFileSync } from "node:child_process";
import { loadDashboardData } from "@/lib/data";
import { buildMonitorView } from "@/lib/monitor";
import Monitor from "@/components/monitor/Monitor";
import "./monitor.css";
const commit =
  process.env.GITHUB_SHA ??
  execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
export const metadata = { other: { "build-commit": commit } };
// Static export reads the production-generated artifacts on EVERY build,
// including the existing weekly data-commit / Pages deployment path.
export default function Home() {
  return <Monitor view={buildMonitorView(loadDashboardData())} />;
}
