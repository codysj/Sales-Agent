import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Flat config. Type-aware linting is on: the value of TypeScript here is the typed contract with
 * the backend (§23), and rules that cannot see types would miss exactly the mistakes that
 * contract exists to prevent.
 */

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  // `configs.flat["recommended-latest"]`, not `configs["recommended-latest"]`: the latter is
  // still the eslintrc shape, where `plugins` is an array of names, and ESLint 10 refuses it.
  reactHooks.configs.flat["recommended-latest"],
  {
    languageOptions: {
      parserOptions: {
        // This file is the only source ESLint reads that `tsconfig.json` does not include — the
        // `.ts` configs are covered by its `**/*.ts` glob, and naming them here as well is an
        // error. It is a build input, not an application source, so it is named explicitly
        // rather than by widening what TypeScript compiles.
        projectService: { allowDefaultProject: ["eslint.config.mjs"] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // This file is not an application source: it is outside `tsconfig.json`, so the type-aware
    // rules see `error` where they want types and report every line of it. Turning them off
    // here is the standard treatment for config files — and it is scoped to this one file, so
    // everything the dashboard actually ships still gets the full type-aware set.
    files: ["eslint.config.mjs"],
    extends: [tseslint.configs.disableTypeChecked],
  },
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      // The dashboard is the approval authority (§12.3, ADR-006). A silently swallowed promise
      // is a review action that looks like it happened and did not.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
    },
  },
);
