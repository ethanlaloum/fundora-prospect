import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// L'API tourne en boucle locale et n'est jointe que par ce proxy. Deux raisons,
// et la seconde n'est pas du confort : elle sert `cedant_denomination`, qui EST
// un nom de personne sur ~20 % des cedants (contrainte 4). L'hote reste donc en
// 127.0.0.1 des deux cotes — serveur Vite comme cible.
//
// La contrainte 2 ne s'y oppose pas : elle interdit de COLLECTER hors des deux
// domaines publics autorises. Parler a notre propre back-end n'est pas une
// collecte, et le transport HTTP du coeur, lui, continue de refuser tout autre
// domaine.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (chemin) => chemin.replace(/^\/api/, ""),
      },
    },
  },
});
