import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { InstallForm } from "../InstallForm";
import { installPackages } from "@/api/install";

vi.mock("@/api/install", () => ({
  installPackages: vi.fn(),
}));

vi.mock("@/components/ui/sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderForm(output: string, scriptId = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InstallForm scriptId={scriptId} output={output} />
    </QueryClientProvider>,
  );
}

describe("InstallForm", () => {
  beforeEach(() => {
    (installPackages as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      output: "Installed foo",
      installed: ["foo"],
    });
  });

  it("shows install input and button", () => {
    renderForm("");
    expect(screen.getByTestId("install-input")).toBeInTheDocument();
    expect(screen.getByTestId("install-button")).toBeInTheDocument();
  });

  it("suggests missing modules parsed from log", () => {
    const output =
      "ModuleNotFoundError: No module named 'boto3'\n" +
      "ModuleNotFoundError: No module named 'requests'\n";
    renderForm(output);
    expect(screen.getByTestId("install-suggest-boto3")).toBeInTheDocument();
    expect(screen.getByTestId("install-suggest-requests")).toBeInTheDocument();
  });

  it("suggests node modules from Cannot find module", () => {
    const output = "Error: Cannot find module 'lodash'";
    renderForm(output);
    expect(screen.getByTestId("install-suggest-lodash")).toBeInTheDocument();
  });

  it("dedupes duplicate suggestions", () => {
    const output =
      "ModuleNotFoundError: No module named 'boto3'\n" +
      "ModuleNotFoundError: No module named 'boto3'\n";
    renderForm(output);
    expect(screen.getAllByTestId("install-suggest-boto3")).toHaveLength(1);
  });

  it("submits a single package from the input on click", async () => {
    renderForm("");
    fireEvent.change(screen.getByTestId("install-input"), { target: { value: "boto3" } });
    fireEvent.click(screen.getByTestId("install-button"));
    await waitFor(() => {
      expect(installPackages).toHaveBeenCalledWith(7, ["boto3"]);
    });
  });

  it("submits multiple space-separated packages", async () => {
    renderForm("");
    fireEvent.change(screen.getByTestId("install-input"), {
      target: { value: "boto3 requests" },
    });
    fireEvent.click(screen.getByTestId("install-button"));
    await waitFor(() => {
      expect(installPackages).toHaveBeenCalledWith(7, ["boto3", "requests"]);
    });
  });

  it("disables button while pending and when input is empty", () => {
    renderForm("");
    const btn = screen.getByTestId("install-button");
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByTestId("install-input"), { target: { value: "x" } });
    expect(btn).not.toBeDisabled();
  });
});
