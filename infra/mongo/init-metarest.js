// First initialization of a fresh production volume. No real secrets in source.
const appDb = db.getSiblingDB("metarest");
const username = process.env.MONGO_APP_USER || "metarest_app";
const password = process.env.MONGO_APP_PASSWORD;
if (!password) throw new Error("MONGO_APP_PASSWORD is required");
const appendOnly = new Set(["decisions", "audit_log"]);
const collections = ["users", "projects", "api_contexts", "prompt_templates", "settings",
                     "runs", "candidates", "decisions", "audit_log"];
const privileges = collections.map(collection => ({
  resource: { db: "metarest", collection },
  actions: ["find", "insert", "createCollection", "createIndex", "listIndexes",
            ...(appendOnly.has(collection) ? [] : ["update", "remove"])],
}));
privileges.push({ resource: { db: "metarest", collection: "" }, actions: ["listCollections"] });
privileges.push({ resource: { db: "metarest", collection: "Record" }, actions: ["listIndexes", "createIndex", "createCollection"] });
appDb.createRole({ role: "metarestApp", privileges, roles: [] });
appDb.createUser({ user: username, pwd: password, roles: [{ role: "metarestApp", db: "metarest" }] });
