/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./accounts/**/*.py",
    "./catalog/**/*.py",
    "./orders/**/*.py",
    "./payments/**/*.py",
    "./api/**/*.py",
    "./static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        leaf: "#2f6f1d",
        mint: "#edf7e8",
        soil: "#805336",
        rice: "#f4c95d",
        ink: "#17211d",
      },
      boxShadow: {
        soft: "0 10px 28px rgba(23, 33, 29, 0.08)",
      },
    },
  },
  plugins: [],
};
