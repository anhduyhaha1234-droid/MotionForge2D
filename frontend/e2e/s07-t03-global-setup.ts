import { readFileSync, writeFileSync } from "fs";

const TMP_ROOT = "C:/Users/Admin/AppData/Local/Temp/s07t03-real-vertical";
const SEED_PATH = TMP_ROOT + "/seed.json";

/**
 * The backend webServer command (frontend/e2e/s07-t03-boot-backend.py)
 * wipes + seeds the temp root BEFORE uvicorn opens SQLite (Windows EPERM:
 * rmSync fails while the DB is open). By globalSetup time the seed already
 * exists — verify it and surface it to the specs.
 */
export default async function globalSetup() {
  const data = JSON.parse(readFileSync(SEED_PATH, "utf-8"));
  writeFileSync(TMP_ROOT + "/seed.json", JSON.stringify(data, null, 2));
  console.log("Seed verified from boot wrapper:", data.projectId);
}
