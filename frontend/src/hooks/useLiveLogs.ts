import { useEffect, useRef, useState } from "react";

export type LogEvent =
  | { kind: "line"; offset: number; text: string }
  | { kind: "end"; status: string; exit_code: number }
  | { kind: "heartbeat" };

export function useLiveLogs(runId: number | null): {
  events: LogEvent[]; ended: boolean;
} {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [ended, setEnded] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (runId == null) return;
    const token = localStorage.getItem("scriptdeck_token");
    // EventSource can't set Authorization header — pass token via query.
    const url = `/api/runs/${runId}/log/stream?token=${encodeURIComponent(token ?? "")}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("line", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setEvents((prev) => [...prev, { kind: "line", offset: data.offset, text: data.text }]);
    });
    es.addEventListener("end", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setEvents((prev) => [...prev, { kind: "end", status: data.status, exit_code: data.exit_code }]);
      setEnded(true);
      es.close();
    });
    es.onerror = () => {
      // auto-reconnect handled by browser; if ended, we won't reopen
    };

    return () => { es.close(); };
  }, [runId]);

  return { events, ended };
}
