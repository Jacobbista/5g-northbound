// Bake env.contract.yaml -> dist/contract.json at build time so the static
// nginx image can serve GET /contract in the same shape as the FastAPI
// services. The contract is schema only (variable names, kinds), never
// runtime values, so a build-time bake is correct - unlike env-config.js,
// which carries runtime config and is generated at container start.
import { readFileSync, writeFileSync } from "node:fs";
import yaml from "js-yaml";

const raw =
  yaml.load(readFileSync(new URL("../env.contract.yaml", import.meta.url), "utf8")) || {};

// Strip value-bearing fields from sensitive entries: the contract is schema
// only, never a value for a secret field.
const sanitize = (entries) =>
  (entries ?? []).map((e) => {
    if (e && e.sensitive) {
      const { default: _d, example: _x, ...rest } = e;
      return rest;
    }
    return e;
  });

const out = {
  service: raw.service ?? null,
  kind: raw.kind ?? null,
  external_origin: raw.external_origin ?? null,
  description: raw.description ?? null,
  env: {
    required: sanitize(raw.required),
    recommended: sanitize(raw.recommended),
    optional: sanitize(raw.optional),
  },
};

writeFileSync(
  new URL("../dist/contract.json", import.meta.url),
  JSON.stringify(out, null, 2)
);
console.log("gen-contract: wrote dist/contract.json");
