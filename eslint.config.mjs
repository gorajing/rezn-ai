import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Non-JS toolchain dirs that must never be linted (root fix, not per-run):
    // the Python virtualenv ships bundled vendor JS (jquery, polyfile templates)
    // that otherwise floods eslint with parse errors and warnings.
    ".venv/**",
    "node_modules/**",
  ]),
]);

export default eslintConfig;
