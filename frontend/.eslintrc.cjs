module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  ignorePatterns: [
    "dist/**",
    "node_modules/**",
    "tests/**",
    "playwright.config.ts",
    "vite.config.ts",
    "*.config.js",
    "*.config.ts",
  ],
  rules: {
    "no-unused-vars": "off",
    "no-undef": "off",
    "no-empty": ["error", { allowEmptyCatch: true }],
  },
};
