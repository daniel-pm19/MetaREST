import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { demoAccounts } from "../api/client";
import { AuthProvider } from "../auth";
import { Login } from "./Login";

const setup = () =>
  render(
    <AuthProvider>
      <Login />
    </AuthProvider>,
  );

describe("Login", () => {
  it("pide correo y contraseña antes de enviar", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /iniciar sesión|entrar/i }));
    expect(await screen.findByText(/escribe tu correo y tu contraseña/i)).toBeInTheDocument();
  });

  it("muestra el error del servidor con credenciales malas", async () => {
    setup();
    await userEvent.type(screen.getByLabelText(/correo/i), demoAccounts[0].email);
    await userEvent.type(screen.getByLabelText(/contraseña/i, { selector: "input" }), "incorrecta");
    await userEvent.click(screen.getByRole("button", { name: /iniciar sesión|entrar/i }));
    await waitFor(() => expect(screen.getByText(/incorrectos/i)).toBeInTheDocument());
  });
});
