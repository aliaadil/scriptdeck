import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FileTree } from "../FileTree";

const files = [
  { path: "main.py", size: 10, updated_at: "2026-08-17T00:00:00Z" },
  { path: ".env", size: 0, updated_at: "2026-08-17T00:00:00Z" },
  { path: "src/utils.py", size: 5, updated_at: "2026-08-17T00:00:00Z" },
];

describe("FileTree", () => {
  it("renders files and marks active", () => {
    render(
      <FileTree
        files={files}
        active="main.py"
        onSelect={() => {}}
        onAdd={() => {}}
        onUpload={() => {}}
        onDelete={() => {}}
        language="python"
      />
    );
    expect(screen.getByText("main.py")).toBeInTheDocument();
    expect(screen.getByText(".env")).toBeInTheDocument();
    expect(screen.getByText("utils.py")).toBeInTheDocument();
    expect(screen.getByText("main.py").closest("[data-active]")).toHaveAttribute("data-active", "true");
  });

  it("calls onSelect when file clicked", () => {
    const onSelect = vi.fn();
    render(
      <FileTree
        files={files}
        active={null}
        onSelect={onSelect}
        onAdd={() => {}}
        onUpload={() => {}}
        onDelete={() => {}}
        language="python"
      />
    );
    fireEvent.click(screen.getByText("main.py"));
    expect(onSelect).toHaveBeenCalledWith("main.py");
  });

  it("renders a 'deps' badge on requirements.txt for python scripts", () => {
    const files = [
      { path: "main.py", size: 0, updated_at: "" },
      { path: "requirements.txt", size: 0, updated_at: "" },
    ];
    render(
      <FileTree
        files={files}
        active="main.py"
        onSelect={() => {}}
        onAdd={() => {}}
        onUpload={() => {}}
        onDelete={() => {}}
        language="python"
      />,
    );
    expect(screen.getByTestId("deps-badge")).toBeInTheDocument();
  });
});