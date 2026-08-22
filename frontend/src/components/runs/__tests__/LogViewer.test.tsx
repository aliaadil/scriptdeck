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
});
