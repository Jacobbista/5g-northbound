import { useEffect, useState } from "react";
import { CAMARA_API_BASE, DEVICE_PHONE_NUMBER } from "../config";

const POLL_INTERVAL_MS = 2000;
const RETRIEVE_PATH = "/location-retrieval/v0.5/retrieve";

export function usePosition(token) {
  const [position, setPosition] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;

    const poll = async () => {
      try {
        const resp = await fetch(`${CAMARA_API_BASE}${RETRIEVE_PATH}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ device: { phoneNumber: DEVICE_PHONE_NUMBER } }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        setPosition(data);
        setError(null);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [token]);

  return { position, error, loading };
}
