import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoleBadge, ScoreChip, StatusBadge } from "./ui";

describe("componentes de interfaz", () => {
  it("RoleBadge muestra la etiqueta en español", () => {
    render(<RoleBadge role="qa" />);
    expect(screen.getByText("Auditor QA")).toBeInTheDocument();
  });
  it("StatusBadge muestra el estado", () => {
    render(<StatusBadge status="pending_review" />);
    expect(screen.getByText(/pendiente/i)).toBeInTheDocument();
  });
  it("ScoreChip muestra el porcentaje", () => {
    render(<ScoreChip value={0.82} />);
    expect(screen.getByText(/82/)).toBeInTheDocument();
  });
});
