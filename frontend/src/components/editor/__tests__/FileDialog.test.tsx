import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { FileDialog } from "../FileDialog";

describe("FileDialog", () => {
  it("rejects bad path", () => {
    const onSubmit = vi.fn();
    render(<FileDialog mode="add" onSubmit={onSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getByTestId("file-path-input"), { target: { value: "../etc/passwd" } });
    fireEvent.click(screen.getByTestId("file-path-submit"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/cannot start with/)).toBeInTheDocument();
  });

  it("accepts good path", () => {
    const onSubmit = vi.fn();
    render(<FileDialog mode="add" onSubmit={onSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getByTestId("file-path-input"), { target: { value: "src/utils.py" } });
    fireEvent.click(screen.getByTestId("file-path-submit"));
    expect(onSubmit).toHaveBeenCalledWith("src/utils.py");
  });
});
