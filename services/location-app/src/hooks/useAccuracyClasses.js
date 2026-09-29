import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

// The accuracy-class vocabulary the gateway publishes, read once. It names the
// bounds of each class an adapter can declare. null until it arrives or when
// the gateway cannot serve it: the bounds then fall back to the deployment
// threshold.
export function useAccuracyClasses() {
  const [vocabulary, setVocabulary] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetch(`${CAMARA_API_BASE}/contracts/accuracy-class-vocabulary.json`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((body) => {
        if (!cancelled) setVocabulary(body);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return vocabulary;
}
