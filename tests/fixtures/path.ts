import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
export const fixturePath = path.join(
  os.tmpdir(),
  "nowcast-monitor-" +
    createHash("sha256").update(process.cwd()).digest("hex").slice(0, 12) +
    ".json",
);
