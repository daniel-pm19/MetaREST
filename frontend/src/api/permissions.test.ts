import { describe, expect, it } from "vitest";
import { permissionsFor } from "./admin";

describe("permissionsFor", () => {
  it("admin tiene control total", () => {
    expect(permissionsFor("admin")).toEqual({ decide: true, launchRun: true, manageProjects: true, admin: true });
  });
  it("qa decide y lanza pero no administra", () => {
    expect(permissionsFor("qa")).toEqual({ decide: true, launchRun: true, manageProjects: true, admin: false });
  });
  it("observer y sin sesión solo leen", () => {
    const none = { decide: false, launchRun: false, manageProjects: false, admin: false };
    expect(permissionsFor("observer")).toEqual(none);
    expect(permissionsFor(undefined)).toEqual(none);
  });
});
