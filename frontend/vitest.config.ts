import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // `.tsx` too, since `T-064`: the review card is a component, and its test renders it.
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    environment: "node",
  },
});
