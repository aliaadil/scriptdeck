import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FileTree } from "../FileTree";

const files = [
  { path: "main.py", size: 10, updated_at: "2026-08-17T00:00:00Z" },
  { path: ".env", size: 0, updated_at: "2026-08-17T00:00:00Z" },
  { path: "src/utils.py", size: 5, updated_at: "2026-08-17T00:00:00Z" },
];

const baseProps = {
  entrypoint: "main.py",
  entrypointOptions: ["main.py", "src/utils.py"],
  onEntrypointChange: () => {},
};

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
        {...baseProps}
      />
    );
    // The file button lives inside the <ul>; the entrypoint <select> also
    // renders "main.py", so scope to the list to disambiguate.
    const list = screen.getByTestId("file-tree").querySelector("ul")!;
    expect(within(list).getByRole("button", { name: "main.py" })).toBeInTheDocument();
    expect(within(list).getByText(".env")).toBeInTheDocument();
    expect(within(list).getByText("utils.py")).toBeInTheDocument();
    expect(
      within(list).getByRole("button", { name: "main.py" }).closest("[data-active]"),
    ).toHaveAttribute("data-active", "true");
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
        {...baseProps}
      />
    );
    const list = screen.getByTestId("file-tree").querySelector("ul")!;
    fireEvent.click(within(list).getByRole("button", { name: "main.py" }));
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
        {...baseProps}
        entrypointOptions={["main.py"]}
      />,
    );
    expect(screen.getByTestId("deps-badge")).toBeInTheDocument();
  });

  it("renders an entrypoint selector with the current entrypoint", () => {
    render(
      <FileTree
        files={files}
        active="main.py"
        onSelect={() => {}}
        onAdd={() => {}}
        onUpload={() => {}}
        onDelete={() => {}}
        language="python"
        {...baseProps}
      />,
    );
    const select = screen.getByTestId("entrypoint-select") as HTMLSelectElement;
    expect(select.value).toBe("main.py");
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      "main.py",
      "src/utils.py",
    ]);
  });

  it("calls onEntrypointChange when a different entrypoint is picked", () => {
    const onEntrypointChange = vi.fn();
    render(
      <FileTree
        files={files}
        active="main.py"
        onSelect={() => {}}
        onAdd={() => {}}
        onUpload={() => {}}
        onDelete={() => {}}
        language="python"
        {...baseProps}
        onEntrypointChange={onEntrypointChange}
      />,
    );
    fireEvent.change(screen.getByTestId("entrypoint-select"), {
      target: { value: "src/utils.py" },
    });
    expect(onEntrypointChange).toHaveBeenCalledWith("src/utils.py");
  });
});