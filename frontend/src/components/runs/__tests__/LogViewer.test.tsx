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

  it("unwraps a JSON envelope with a 'content' string field", () => {
    const text = '{"content": "Hello from Kindling (api_key length: 4)\\n"}';
    render(<LogViewer text={text} />);
    expect(
      screen.getByText(/Hello from Kindling/),
    ).toBeInTheDocument();
    // The JSON envelope should NOT render as raw JSON.
    expect(screen.queryByText(/"content":/)).not.toBeInTheDocument();
  });

  it("unwraps envelopes with message/msg/text/data keys too", () => {
    const text = '{"message": "build ok", "msg": "deploy", "text": "readme", "data": "payload"}';
    render(<LogViewer text={text} />);
    // First matched envelope wins; just assert no JSON envelope rendered.
    expect(screen.queryByText(/"message":/)).not.toBeInTheDocument();
  });

  it("keeps pretty-print for JSON without an envelope string field", () => {
    const text = '{"foo": 1, "bar": [2, 3]}';
    render(<LogViewer text={text} />);
    expect(screen.getByText(/foo/)).toBeInTheDocument();
    expect(screen.getByText(/\[/)).toBeInTheDocument();
  });

  it("splits embedded newlines inside an envelope string into separate rows", () => {
    // Use String.raw so the input contains literal "\n" (backslash-n).
    // JSON.parse turns the escape sequence inside the string into a real
    // newline, which is what we want to split on after unwrapping.
    const text = String.raw`{"content":"1234\nHello from Kindling (api_key length: 4)\n"}`;
    const { container } = render(<LogViewer text={text} />);
    const rowContainer = container.querySelector(".space-y-1.font-mono");
    expect(rowContainer).not.toBeNull();
    const rows = rowContainer!.querySelectorAll(":scope > div");
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toBe("1234");
    expect(rows[1].textContent).toBe(
      "Hello from Kindling (api_key length: 4)",
    );
    expect(screen.queryByText(/"content":/)).not.toBeInTheDocument();
  });
});
