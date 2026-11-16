import { render } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth";
import { Login } from "./Login";

// jsdom no calcula contraste ni layout: esta prueba cubre etiquetas, roles ARIA y estructura.
const audit = (el: HTMLElement) => axe.run(el, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });

describe("accesibilidad (axe)", () => {
  it("Login no tiene violaciones", async () => {
    const { container } = render(
      <AuthProvider>
        <Login />
      </AuthProvider>,
    );
    const { violations } = await audit(container);
    expect(violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});
