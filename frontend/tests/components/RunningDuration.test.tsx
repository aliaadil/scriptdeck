import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { RunningDuration } from "@/components/runs/RunningDuration";

describe("RunningDuration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders seconds when fresh", () => {
    render(<RunningDuration started_at="2030-01-01T00:00:00Z" status="running" />);
    expect(screen.getByText(/0\.0s|0s/)).toBeInTheDocument();
  });

  it("ticks forward after 2s", () => {
    const { rerender } = render(
      <RunningDuration started_at="2030-01-01T00:00:00Z" status="running" />,
    );
    act(() => {
      vi.setSystemTime(new Date("2030-01-01T00:00:02Z"));
    });
    rerender(<RunningDuration started_at="2030-01-01T00:00:00Z" status="running" />);
    expect(screen.getByText(/2s/)).toBeInTheDocument();
  });

  it("renders minutes when past 60s", () => {
    render(<RunningDuration started_at="2029-12-31T23:58:30Z" status="running" />);
    expect(screen.getByText(/1m 30s/)).toBeInTheDocument();
  });

  it("renders hours when past 1h", () => {
    render(<RunningDuration started_at="2029-12-31T22:55:00Z" status="running" />);
    expect(screen.getByText(/1h 5m/)).toBeInTheDocument();
  });

  it("renders days when past 24h", () => {
    render(<RunningDuration started_at="2029-12-30T00:00:00Z" status="running" />);
    expect(screen.getByText(/2d 0h/)).toBeInTheDocument();
  });

  it("cleans up interval on unmount", () => {
    const spy = vi.spyOn(global, "clearInterval");
    const { unmount } = render(
      <RunningDuration started_at="2030-01-01T00:00:00Z" status="running" />,
    );
    unmount();
    expect(spy).toHaveBeenCalled();
  });

  it("does not tick when status is success", () => {
    render(
      <RunningDuration
        started_at="2030-01-01T00:00:00Z"
        ended_at="2030-01-01T00:00:05Z"
        status="success"
      />,
    );
    expect(screen.getByText(/5s/)).toBeInTheDocument();
    act(() => {
      vi.setSystemTime(new Date("2030-01-01T00:00:30Z"));
    });
    // Same render — the 5s value must remain static because status is success.
    expect(screen.getByText(/5s/)).toBeInTheDocument();
  });

  it("does not tick when status is failure", () => {
    render(
      <RunningDuration
        started_at="2030-01-01T00:00:00Z"
        ended_at="2030-01-01T00:00:10Z"
        status="failure"
      />,
    );
    expect(screen.getByText(/10s/)).toBeInTheDocument();
    act(() => {
      vi.setSystemTime(new Date("2030-01-01T00:05:00Z"));
    });
    expect(screen.getByText(/10s/)).toBeInTheDocument();
  });

  it("renders — when status is not running and ended_at missing", () => {
    render(<RunningDuration started_at="2030-01-01T00:00:00Z" status="success" />);
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  it("does not start an interval when status is not running", () => {
    const spy = vi.spyOn(global, "setInterval");
    render(
      <RunningDuration
        started_at="2030-01-01T00:00:00Z"
        ended_at="2030-01-01T00:00:05Z"
        status="success"
      />,
    );
    expect(spy).not.toHaveBeenCalled();
  });
});
