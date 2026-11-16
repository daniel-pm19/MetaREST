import { describe, expect, it } from "vitest";
import { formatUsd, parsePrices, runCost } from "./cost";

const run = (stages: object[]) => ({ report: { generation_model: "gen", verification_model: "ver", warnings: [], stages } }) as never;
const prices = { gen: { input: 3, output: 15 }, ver: { input: 1, output: 5 } };

describe("parsePrices", () => {
  it("ignora JSON inválido y entradas incompletas", () => {
    expect(parsePrices(undefined)).toEqual({});
    expect(parsePrices("{no json")).toEqual({});
    expect(parsePrices('{"a":{"input":1,"output":2},"b":{"input":1}}')).toEqual({ a: { input: 1, output: 2 } });
  });
});

describe("runCost", () => {
  it("usa el modelo de generación o de verificación según la etapa", () => {
    const r = run([
      { name: "generate", usage: { input_tokens: 1_000_000, output_tokens: 100_000 } },
      { name: "semantic", usage: { input_tokens: 2_000_000, output_tokens: 0 } },
    ]);
    expect(runCost(r, prices)).toBeCloseTo(3 + 1.5 + 2);
  });
  it("devuelve null si falta el precio de un modelo usado o no hubo uso", () => {
    expect(runCost(run([{ name: "generate", usage: { input_tokens: 10, output_tokens: 10 } }]), {})).toBeNull();
    expect(runCost(run([{ name: "extract" }]), prices)).toBeNull();
  });
});

describe("formatUsd", () => {
  it("muestra 4 decimales para costos pequeños", () => {
    expect(formatUsd(0.0042)).toBe("US$ 0.0042");
    expect(formatUsd(1.5)).toBe("US$ 1.50");
  });
});
