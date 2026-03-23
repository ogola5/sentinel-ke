/**
 * useEventStream — SSE hook for the Sentinel-KE real-time threat event stream.
 *
 * Connects to GET /v1/stream/events?token=<apiKey>
 * Maintains a rolling buffer of the most recent events.
 * Auto-reconnects with exponential backoff on error.
 *
 * Usage:
 *   const { liveEvents, streamStatus } = useEventStream();
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { EventRecord } from "../types/domain";
import { loadClientCredentials } from "../api/client";
import { endpoints } from "../api/endpoints";

export type StreamStatus = "connecting" | "live" | "error" | "closed";

const MAX_BUFFER   = 80;   // max events to keep in memory
const MAX_RETRY    = 8;    // after this many retries, give up and stay in error

/**
 * @param enabled - set false to disable the stream (e.g. on screens that don't need it)
 */
export function useEventStream(enabled = true) {
  const [liveEvents,   setLiveEvents]   = useState<EventRecord[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("connecting");

  const esRef        = useRef<EventSource | null>(null);
  const retryCount   = useRef(0);
  const retryTimer   = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const { apiKey } = loadClientCredentials();
    const url = endpoints.eventStream(apiKey);

    setStreamStatus("connecting");
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setStreamStatus("live");
      retryCount.current = 0;
    };

    es.onmessage = (evt) => {
      try {
        const record = JSON.parse(evt.data) as EventRecord;
        setLiveEvents((prev) => {
          // Deduplicate by event_hash; newest first
          if (prev.some((e) => e.event_hash === record.event_hash)) return prev;
          const next = [record, ...prev];
          return next.length > MAX_BUFFER ? next.slice(0, MAX_BUFFER) : next;
        });
      } catch {
        // malformed message — ignore
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setStreamStatus("error");

      if (retryCount.current >= MAX_RETRY) return; // give up

      // Exponential back-off: 2s → 4s → 8s → … → 30s cap
      const delay = Math.min(2_000 * 2 ** retryCount.current, 30_000);
      retryCount.current += 1;
      retryTimer.current = setTimeout(connect, delay);
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    connect();
    return () => {
      esRef.current?.close();
      if (retryTimer.current) clearTimeout(retryTimer.current);
      setStreamStatus("closed");
    };
  }, [connect, enabled]);

  return { liveEvents, streamStatus };
}
