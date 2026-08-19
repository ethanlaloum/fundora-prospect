import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

const racine = document.getElementById("racine");
if (!racine) {
  // « introuvable » plutot que le synonyme evident : celui-la est un motif de
  // refus du coeur, et le verrou de vocabulaire le signale ou qu'il apparaisse
  // — y compris dans un commentaire, y compris dans celui qui l'explique.
  // Reformuler coute une seconde ; affaiblir le verrou couterait la garantie.
  throw new Error("element #racine introuvable dans index.html");
}

createRoot(racine).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
