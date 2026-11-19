import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
export const fixturePath = process.env.NOWCAST_FIXTURE_DIR
  ? path.resolve(process.env.NOWCAST_FIXTURE_DIR, "monitor.json")
  : path.join(
  os.tmpdir(),
  "nowcast-monitor-" +
    createHash("sha256").update(process.cwd()).digest("hex").slice(0, 12) +
    ".json",
);
