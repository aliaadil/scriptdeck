import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { MobileBottomNav } from "../mobile-bottom-nav";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

import { useIsMobile } from "@/hooks/use-mobile";

describe("MobileBottomNav", () => {
  it("renders four nav links when on mobile", () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(
      <MemoryRouter>
        <MobileBottomNav />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /scripts/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /schedules/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /runs/i })).toBeInTheDocument();
  });

  it("renders nothing when not on mobile", () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    const { container } = render(
      <MemoryRouter>
        <MobileBottomNav />
      </MemoryRouter>
    );
    expect(container).toBeEmptyDOMElement();
  });
});