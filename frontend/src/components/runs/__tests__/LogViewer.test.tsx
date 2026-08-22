import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import { LogViewer } from "../LogViewer";

describe("LogViewer", () => {
  it("renders plain text", () => {
    render(<LogViewer text={"hello\nworld"} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
  });

  it("pretty-prints a JSON line", () => {
    const text = '{"foo": 1, "bar": [2, 3]}';
    render(<LogViewer text={text} />);
    expect(screen.getByText(/foo/)).toBeInTheDocument();
    expect(screen.getByText(/\[/)).toBeInTheDocument();
  });

  it("toggles to raw view", async () => {
    const user = userEvent.setup();
    render(<LogViewer text="line one" />);
    await user.click(screen.getByRole("button", { name: /view raw/i }));
    expect(document.querySelector("pre")?.textContent).toContain("line one");
  });
});
