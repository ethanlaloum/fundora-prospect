// GENERE par tools/exporter_types.py — NE PAS EDITER A LA MAIN.
//
// Les types viennent de reponses REELLES de l'API, pas d'une recopie du modele
// Python. `tests/test_types_web.py` regenere ce fichier et echoue s'il differe,
// et refuse un schema deduit d'un corpus qui n'exerce pas tous les champs.
//
// Pour le mettre a jour :  python tools/exporter_types.py

export interface ReponseCollecte {
  compteurs: null | {
    annonces_exploitables: number;
    annonces_publiees: number;
    annonces_rapatriees: number;
    collecte_partielle: boolean;
    plafond_atteint: boolean;
    sans_cedant_ou_illisibles: number;
  };
  departements: string[];
  reserve: null | string;
}

export interface ReponseComparatif {
  analyse: {
    disponible: boolean;
    par_lead: Record<string, string>;
    reserve: null | string;
    synthese: string;
  };
  effet_du_modele: {
    arguments_respectes: boolean;
    identiques: boolean;
    meme_ordre: boolean;
    seulement_comparee: string[];
    seulement_reference: string[];
  };
  fraicheur_de_la_base: {
    disponible: boolean;
    identiques: boolean;
    meme_ordre: boolean;
    reserve: string;
    seulement_comparee: string[];
    seulement_reference: string[];
  };
  leads: Array<{
    breakdown: Array<{
      critere: string;
      motif: string;
      poids: number;
      points: number;
    }>;
    cedant: string;
    code_ape: string;
    date_acte: null | string;
    date_parution: string;
    date_reference: string;
    departement: string;
    id: string;
    jours_ecoules: number;
    montant_eur: number;
    provenance: {
      base_legale: string;
      date_collecte: string;
      source: string;
      url_publication: string;
    };
    score: number;
    section_ape: string;
    siren: null | string;
    statut_cedant: string;
    statut_motif: string;
    type_cedant: string;
    type_cedant_libelle: string;
    url_publication: string;
  }>;
  parametres: {
    departement: string;
    limite: number;
    mois: number;
    montant_min: number;
  };
  voies: {
    agent: {
      ids: string[];
      mesure: {
        appels_outil: Record<string, number | string>[];
        duree_ms: number;
        ids_rendus: string[];
        modele: string;
        tokens_cache_lus: number;
        tokens_entree: number;
        tokens_sortie: number;
        tours: number;
      };
    };
    base: {
      ids: string[];
      mesure: {
        duree_ms: number;
      };
    };
    direct: {
      ids: string[];
      mesure: {
        duree_ms: number;
      };
    };
  };
}

export interface ReponseEcartes {
  correspondants: number;
  departements: string[];
  ecartes: Array<{
    cedant: string;
    date_acte: null | string;
    date_parution: string;
    departement: string;
    devise: string;
    id: string;
    montant_eur: number;
    motif: string;
    siren: null | string;
    statut_cedant: string;
    type_cedant: string;
    type_cedant_libelle: string;
    url_publication: string;
  }>;
  montant_min_eur: number;
  motif: null | string;
  periode: {
    debut: string;
    fin: string;
  };
  rendus: number;
}

export interface ReponseEvenement {
  ecarte: null | {
    cedant: string;
    date_acte: string;
    date_parution: string;
    departement: string;
    devise: string;
    id: string;
    montant_eur: number;
    motif: string;
    siren: null | string;
    statut_cedant: string;
    type_cedant: string;
    type_cedant_libelle: string;
    url_publication: string;
  };
  lead: null | {
    breakdown: Array<{
      critere: string;
      motif: string;
      poids: number;
      points: number;
    }>;
    cedant: string;
    code_ape: null | string;
    date_acte: null | string;
    date_parution: string;
    date_reference: string;
    departement: string;
    id: string;
    jours_ecoules: number;
    montant_eur: number;
    provenance: {
      base_legale: string;
      date_collecte: string;
      source: string;
      url_publication: string;
    };
    score: number;
    section_ape: null | string;
    siren: null | string;
    statut_cedant: string;
    statut_motif: string;
    type_cedant: string;
    type_cedant_libelle: string;
    url_publication: string;
  };
  revisions: Array<{
    contenu: Record<string, number | string>;
    remplacee_a: string;
  }>;
  transitions: Array<{
    motif: string;
    observe_a: string;
    siren: string;
    sortie_du_flux: boolean;
    statut_apres: string;
    statut_avant: string;
  }>;
}

export interface ReponseFiltres {
  filtres: Array<{
    defaut: number | string;
    description: string;
    maximum: null | number;
    minimum: null | number;
    nom: string;
  }>;
}

export interface ReponseHypothese {
  breakdown: Array<{
    critere: string;
    motif: string;
    poids: number;
    points: number;
  }>;
  classable: boolean;
  motif_refus: null | string;
  score: null | number;
}

export interface ReponseLeads {
  departements: string[];
  leads: Array<{
    breakdown: Array<{
      critere: string;
      motif: string;
      poids: number;
      points: number;
    }>;
    cedant: string;
    code_ape: null | string;
    date_acte: null | string;
    date_parution: string;
    date_reference: string;
    departement: string;
    id: string;
    jours_ecoules: number;
    montant_eur: number;
    provenance: {
      base_legale: string;
      date_collecte: string;
      source: string;
      url_publication: string;
    };
    score: number;
    section_ape: null | string;
    siren: null | string;
    statut_cedant: string;
    statut_motif: string;
    type_cedant: string;
    type_cedant_libelle: string;
    url_publication: string;
  }>;
  montant_min_eur: number;
  periode: {
    debut: string;
    fin: string;
  };
  resume: string;
  statistiques: {
    annonces_exploitables: number;
    annonces_publiees: number;
    annonces_rapatriees: number;
    candidats: number;
    classables: number;
    collecte_partielle: boolean;
    ecartes: Record<string, number>;
    evenements_en_base: number;
    leads_rendus: number;
    plafond_atteint: boolean;
    sans_cedant_ou_illisibles: number;
  };
}

export interface ReponseSorties {
  depuis: null | string;
  sorties: Array<{
    motif: string;
    observe_a: string;
    siren: string;
    sortie_du_flux: boolean;
    statut_apres: string;
    statut_avant: string;
  }>;
  sorties_observees: number;
  transitions_observees: number;
}
