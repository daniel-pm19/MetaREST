import { beforeEach, describe, expect, it } from "vitest";
import { api, ApiError, demoAccounts, isMock, session } from "./client";

const account = (role: string) => demoAccounts.find((a) => a.role === role)!;
async function loginAs(role: string) {
  const a = account(role);
  const res = await api.login(a.email, a.password);
  session.set(res.access_token);
  return res;
}

beforeEach(() => session.set(null));

describe("cliente en modo demostración", () => {
  it("está en modo demo sin VITE_API_URL", () => expect(isMock).toBe(true));

  it("rechaza credenciales incorrectas con 401", async () => {
    await expect(api.login(account("admin").email, "mala")).rejects.toMatchObject({ status: 401 });
  });

  it("el observador no puede decidir: 403", async () => {
    await loginAs("observer");
    const [run] = await api.listRuns("proj_demo");
    const pending = (await api.listCandidates(run.id)).find((c) => c.status === "pending_review")!;
    await expect(api.decide(pending.id, { decision: "accepted" })).rejects.toMatchObject({ status: 403 });
  });

  it("rechazar exige justificación (422) y aceptar funciona para QA", async () => {
    await loginAs("qa");
    const [run] = await api.listRuns("proj_demo");
    const pending = (await api.listCandidates(run.id)).filter((c) => c.status === "pending_review");
    await expect(api.decide(pending[0].id, { decision: "rejected" })).rejects.toMatchObject({ status: 422 });
    await api.decide(pending[0].id, { decision: "accepted", review_time_ms: 1200 });
    await expect(api.decide(pending[0].id, { decision: "accepted" })).rejects.toMatchObject({ status: 409 });
    expect((await api.listDecisions(run.id))[0]).toMatchObject({ candidate_id: pending[0].id, decision: "accepted" });
  });

  it("solo el admin gestiona usuarios y configuración", async () => {
    await loginAs("qa");
    await expect(api.listUsers()).rejects.toBeInstanceOf(ApiError);
    await loginAs("admin");
    expect((await api.listUsers()).length).toBeGreaterThan(0);
  });

  it("no se puede cambiar el propio rol", async () => {
    const { user } = await loginAs("admin");
    await expect(api.updateUser(user.id, { role: "observer" })).rejects.toMatchObject({ status: 400 });
  });
});
