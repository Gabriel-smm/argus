/**
 * Fixed text for the scan page and the site report, in English, Spanish and French.
 *
 * Everything is in this file, so it works offline: no translation service is called.
 * The detailed reason and "Next:" text come from data/context/bands.csv in English and
 * are not translated here; the page says "Details in English" next to them.
 */
import { useMemo } from "react";
import { create } from "zustand";

export const LANGUAGES = [
  { code: "en", name: "English", english: "English" },
  { code: "es", name: "Español", english: "Spanish" },
  { code: "fr", name: "Français", english: "French" },
] as const;

export type Language = (typeof LANGUAGES)[number]["code"];

const EN = {
  "language.choose": "Language",
  "app.local": "Running locally",

  "scan.title": "Scan the area",
  "scan.scanning": "Scanning",
  "scan.listening": "Listening…",
  "scan.thinking": "Making sense of it…",
  "scan.intro":
    "Argus listens to the airwaves and tells you what is normal here, what is not, and what to check next.",
  "scan.listeningAt": "Listening from 88 MHz to 6 GHz at {site}.",
  "scan.thisSite": "this site",
  "scan.found": "Found {n} signals. Checking what each one is and whether it belongs here.",
  "scan.start": "Start scan",
  "scan.again": "Scan again",
  "scan.seeLast": "See last result",
  "scan.spectrum": "Spectrum from 88 MHz to 6 GHz",
  "scan.spectrumFound": "Spectrum from 88 MHz to 6 GHz, {n} signals found so far",
  "scan.heard": "Heard so far",
  "scan.more": "+{n} more",
  "scan.demoBadge": "Demo mode: sample campus signals, not a live radio",
  "scan.andrewBadge": "Demo: illustrative scenario by Andrew, not a real capture",

  "scene.choose": "Scenario",
  "scene.campus": "Campus sample",
  "scene.normal": "Normal day",
  "scene.drone": "Drone nearby",
  "scene.jamming": "Jamming",

  "verdict.jamming": "Possible jamming",

  "demo.badge": "Demo data",
  "demo.tipCampus": "{scene}: sample campus signals",
  "demo.tipAndrew": "{scene}: illustrative scenario by Andrew, not a real capture",
  "demo.controls": "Demo controls",
  "demo.shortcut": "Shortcut: Shift+D",
  "demo.close": "Close",

  "likely.wifi": "Looks like Wi-Fi or Bluetooth",
  "likely.drone": "Possible drone",
  "likely.gps": "Something on GPS",
  "likely.aircraft": "Looks like aircraft radio",
  "likely.radar": "Looks like radar",
  "likely.phone": "Looks like a phone network",
  "likely.sensor": "Looks like a sensor or remote",
  "likely.station": "Looks like a radio station",
  "likely.ham": "Looks like ham radio",
  "likely.restricted": "On the restricted list",
  "likely.mystery": "Mystery signal",
  "likely.signal": "Signal",

  "group.needs_review": "Needs a closer look",
  "group.unknown": "Unknown",
  "group.expected": "Normal here",

  "verdict.review.one": "{n} signal needs a closer look",
  "verdict.review.other": "{n} signals need a closer look",
  "explain.review.one":
    "Most of what we heard is normal for {site}, but {n} signal does not belong here. Tap the red tiles below to see them.",
  "explain.review.other":
    "Most of what we heard is normal for {site}, but {n} signals do not belong here. Tap the red tiles below to see them.",
  "verdict.unknown": "Mostly normal",
  "explain.unknown.one": "Nothing alarming. We could not place {n} signal.",
  "explain.unknown.other": "Nothing alarming. We could not place {n} signals.",
  "verdict.normal": "Normal activity",
  "explain.normal": "Everything we heard is what we would expect at {site}.",

  "report.label": "Site report",
  "report.inAir": "What's in the air",
  "report.worst": ", worst: {group}",
  "report.hint": "Tap a tile to see the signals behind it.",
  "report.hintRed": "Tap a tile to see the signals behind it. Start with the red ones.",
  "report.safety": "Safety band: listen only",
  "report.signal": "signal {id}",
  "report.next": "Next: ",
  "report.showMore": "Show {n} more",
  "report.detailsInEnglish": "Details in English",
  "report.ask": "Ask about any of the {n} signals, or start with a question below.",

  "location.at": "Location: {site} ({lat}, {lon}) · from site profile",
  "location.atNoCoords": "Location: {site} · from site profile",
  "location.gpsWarning": "Location may be unreliable: GPS interference detected nearby.",

  "packet.export": "Package for HQ",
  "packet.exporting": "Packaging…",
  "packet.ready": "Packet ready: {n} signals, {size} KB",
  "packet.fingerprint": "Fingerprint {fp}",
  "packet.failed": "The packet could not be made in this browser.",
  "packet.open": "Open a packet",
  "packet.openedFrom": "Opened from packet {fp}, created {time} at {site}",
  "packet.viewOnly": "View only. The chat still answers about this computer's own scan.",
  "packet.close": "Close packet",
  "packet.changed": "This packet was changed after it was created",
  "packet.invalid": "This file is not an Argus packet.",
} as const;

export type MessageKey = keyof typeof EN;
type Messages = Record<MessageKey, string>;

const ES: Messages = {
  "language.choose": "Idioma",
  "app.local": "Funcionando en este equipo",

  "scan.title": "Explorar la zona",
  "scan.scanning": "Escaneando",
  "scan.listening": "Escuchando…",
  "scan.thinking": "Interpretando lo escuchado…",
  "scan.intro":
    "Argus escucha las ondas y te dice qué es normal aquí, qué no lo es y qué revisar después.",
  "scan.listeningAt": "Escuchando de 88 MHz a 6 GHz en {site}.",
  "scan.thisSite": "este lugar",
  "scan.found": "Se encontraron {n} señales. Comprobando qué es cada una y si es normal aquí.",
  "scan.start": "Iniciar escaneo",
  "scan.again": "Escanear de nuevo",
  "scan.seeLast": "Ver el último resultado",
  "scan.spectrum": "Espectro de 88 MHz a 6 GHz",
  "scan.spectrumFound": "Espectro de 88 MHz a 6 GHz, {n} señales encontradas hasta ahora",
  "scan.heard": "Escuchado hasta ahora",
  "scan.more": "+{n} más",
  "scan.demoBadge": "Modo demo: señales de muestra del campus, no es una radio en vivo",
  "scan.andrewBadge": "Demo: escenario ilustrativo de Andrew, no es una captura real",

  "scene.choose": "Escenario",
  "scene.campus": "Muestra del campus",
  "scene.normal": "Día normal",
  "scene.drone": "Dron cerca",
  "scene.jamming": "Bloqueo de señal",

  "verdict.jamming": "Posible bloqueo de señal",

  "demo.badge": "Datos de demostración",
  "demo.tipCampus": "{scene}: señales de muestra del campus",
  "demo.tipAndrew": "{scene}: escenario ilustrativo de Andrew, no es una captura real",
  "demo.controls": "Controles de demostración",
  "demo.shortcut": "Atajo: Mayús+D",
  "demo.close": "Cerrar",

  "likely.wifi": "Parece Wi-Fi o Bluetooth",
  "likely.drone": "Posible dron",
  "likely.gps": "Algo en la banda GPS",
  "likely.aircraft": "Parece radio de aviación",
  "likely.radar": "Parece un radar",
  "likely.phone": "Parece una red de telefonía",
  "likely.sensor": "Parece un sensor o un control remoto",
  "likely.station": "Parece una emisora de radio",
  "likely.ham": "Parece radioaficionado",
  "likely.restricted": "En la lista restringida",
  "likely.mystery": "Señal misteriosa",
  "likely.signal": "Señal",

  "group.needs_review": "Requiere revisión",
  "group.unknown": "Desconocida",
  "group.expected": "Normal aquí",

  "verdict.review.one": "{n} señal requiere revisión",
  "verdict.review.other": "{n} señales requieren revisión",
  "explain.review.one":
    "Casi todo lo que escuchamos es normal en {site}, pero {n} señal no encaja aquí. Toca las fichas rojas de abajo para verla.",
  "explain.review.other":
    "Casi todo lo que escuchamos es normal en {site}, pero {n} señales no encajan aquí. Toca las fichas rojas de abajo para verlas.",
  "verdict.unknown": "Casi todo normal",
  "explain.unknown.one": "Nada alarmante. No pudimos identificar {n} señal.",
  "explain.unknown.other": "Nada alarmante. No pudimos identificar {n} señales.",
  "verdict.normal": "Actividad normal",
  "explain.normal": "Todo lo que escuchamos es lo esperable en {site}.",

  "report.label": "Informe del lugar",
  "report.inAir": "Qué hay en el aire",
  "report.worst": ", la más grave: {group}",
  "report.hint": "Toca una ficha para ver sus señales.",
  "report.hintRed": "Toca una ficha para ver sus señales. Empieza por las rojas.",
  "report.safety": "Banda de seguridad: solo escuchar",
  "report.signal": "señal {id}",
  "report.next": "Siguiente paso: ",
  "report.showMore": "Mostrar {n} más",
  "report.detailsInEnglish": "Detalles en inglés",
  "report.ask": "Pregunta por cualquiera de las {n} señales o empieza con una pregunta de abajo.",

  "location.at": "Ubicación: {site} ({lat}, {lon}) · según el perfil del lugar",
  "location.atNoCoords": "Ubicación: {site} · según el perfil del lugar",
  "location.gpsWarning": "La ubicación puede no ser fiable: se detectó interferencia GPS cerca.",

  "packet.export": "Empaquetar para la sede",
  "packet.exporting": "Empaquetando…",
  "packet.ready": "Paquete listo: {n} señales, {size} KB",
  "packet.fingerprint": "Huella {fp}",
  "packet.failed": "No se pudo crear el paquete en este navegador.",
  "packet.open": "Abrir un paquete",
  "packet.openedFrom": "Abierto desde el paquete {fp}, creado el {time} en {site}",
  "packet.viewOnly": "Solo lectura. El chat sigue respondiendo sobre el escaneo de este equipo.",
  "packet.close": "Cerrar paquete",
  "packet.changed": "Este paquete se modificó después de crearse",
  "packet.invalid": "Este archivo no es un paquete de Argus.",
};

const FR: Messages = {
  "language.choose": "Langue",
  "app.local": "Fonctionne en local",

  "scan.title": "Analyser la zone",
  "scan.scanning": "Analyse en cours",
  "scan.listening": "Écoute…",
  "scan.thinking": "Interprétation…",
  "scan.intro":
    "Argus écoute les ondes et vous dit ce qui est normal ici, ce qui ne l'est pas et quoi vérifier ensuite.",
  "scan.listeningAt": "Écoute de 88 MHz à 6 GHz : {site}.",
  "scan.thisSite": "ce site",
  "scan.found": "{n} signaux trouvés. Vérification de ce que chacun est et s'il a sa place ici.",
  "scan.start": "Lancer l'analyse",
  "scan.again": "Relancer l'analyse",
  "scan.seeLast": "Voir le dernier résultat",
  "scan.spectrum": "Spectre de 88 MHz à 6 GHz",
  "scan.spectrumFound": "Spectre de 88 MHz à 6 GHz, {n} signaux trouvés jusqu'ici",
  "scan.heard": "Entendu jusqu'ici",
  "scan.more": "+{n} autres",
  "scan.demoBadge": "Mode démo : signaux d'exemple du campus, pas une radio en direct",
  "scan.andrewBadge": "Démo : scénario illustratif d'Andrew, pas une capture réelle",

  "scene.choose": "Scénario",
  "scene.campus": "Échantillon du campus",
  "scene.normal": "Journée normale",
  "scene.drone": "Drone à proximité",
  "scene.jamming": "Brouillage",

  "verdict.jamming": "Brouillage possible",

  "demo.badge": "Données de démo",
  "demo.tipCampus": "{scene} : signaux d'exemple du campus",
  "demo.tipAndrew": "{scene} : scénario illustratif d'Andrew, pas une capture réelle",
  "demo.controls": "Commandes de démo",
  "demo.shortcut": "Raccourci : Maj+D",
  "demo.close": "Fermer",

  "likely.wifi": "Ressemble à du Wi-Fi ou Bluetooth",
  "likely.drone": "Drone possible",
  "likely.gps": "Quelque chose sur le GPS",
  "likely.aircraft": "Ressemble à une radio d'avion",
  "likely.radar": "Ressemble à un radar",
  "likely.phone": "Ressemble à un réseau mobile",
  "likely.sensor": "Ressemble à un capteur ou une télécommande",
  "likely.station": "Ressemble à une station de radio",
  "likely.ham": "Ressemble à un radioamateur",
  "likely.restricted": "Sur la liste restreinte",
  "likely.mystery": "Signal mystère",
  "likely.signal": "Signal",

  "group.needs_review": "À examiner de plus près",
  "group.unknown": "Inconnu",
  "group.expected": "Normal ici",

  "verdict.review.one": "{n} signal à examiner de plus près",
  "verdict.review.other": "{n} signaux à examiner de plus près",
  "explain.review.one":
    "La plupart de ce que nous avons entendu est normal pour {site}, mais {n} signal n'a pas sa place ici. Touchez les cases rouges ci-dessous pour le voir.",
  "explain.review.other":
    "La plupart de ce que nous avons entendu est normal pour {site}, mais {n} signaux n'ont pas leur place ici. Touchez les cases rouges ci-dessous pour les voir.",
  "verdict.unknown": "Plutôt normal",
  "explain.unknown.one": "Rien d'alarmant. Nous n'avons pas pu identifier {n} signal.",
  "explain.unknown.other": "Rien d'alarmant. Nous n'avons pas pu identifier {n} signaux.",
  "verdict.normal": "Activité normale",
  "explain.normal": "Tout ce que nous avons entendu est normal pour {site}.",

  "report.label": "Rapport du site",
  "report.inAir": "Ce qu'il y a dans l'air",
  "report.worst": ", le plus grave : {group}",
  "report.hint": "Touchez une case pour voir ses signaux.",
  "report.hintRed": "Touchez une case pour voir ses signaux. Commencez par les rouges.",
  "report.safety": "Bande de sécurité : écoute seulement",
  "report.signal": "signal {id}",
  "report.next": "Étape suivante : ",
  "report.showMore": "Afficher {n} de plus",
  "report.detailsInEnglish": "Détails en anglais",
  "report.ask": "Posez une question sur l'un des {n} signaux, ou commencez par une question ci-dessous.",

  "location.at": "Position : {site} ({lat}, {lon}) · d'après le profil du site",
  "location.atNoCoords": "Position : {site} · d'après le profil du site",
  "location.gpsWarning": "La position peut être peu fiable : interférence GPS détectée à proximité.",

  "packet.export": "Préparer un paquet pour le QG",
  "packet.exporting": "Préparation…",
  "packet.ready": "Paquet prêt : {n} signaux, {size} Ko",
  "packet.fingerprint": "Empreinte {fp}",
  "packet.failed": "Impossible de créer le paquet dans ce navigateur.",
  "packet.open": "Ouvrir un paquet",
  "packet.openedFrom": "Ouvert depuis le paquet {fp}, créé le {time} à {site}",
  "packet.viewOnly": "Lecture seule. Le chat répond toujours sur l'analyse de cet ordinateur.",
  "packet.close": "Fermer le paquet",
  "packet.changed": "Ce paquet a été modifié après sa création",
  "packet.invalid": "Ce fichier n'est pas un paquet Argus.",
};

const MESSAGES: Record<Language, Messages> = { en: EN, es: ES, fr: FR };

/** Strings the Laya service sends in English (pipeline/lookup.py, pipeline/context.py). */
type Translations = Record<string, { es: string; fr: string }>;

const KINDS: Translations = {
  "Wi-Fi & Bluetooth": { es: "Wi-Fi y Bluetooth", fr: "Wi-Fi et Bluetooth" },
  Drones: { es: "Drones", fr: "Drones" },
  GPS: { es: "GPS", fr: "GPS" },
  Aircraft: { es: "Aviones", fr: "Avions" },
  Radar: { es: "Radar", fr: "Radar" },
  "Phone networks": { es: "Redes de telefonía", fr: "Réseaux mobiles" },
  "Sensors & gadgets": { es: "Sensores y aparatos", fr: "Capteurs et gadgets" },
  "Radio stations": { es: "Emisoras de radio", fr: "Stations de radio" },
  "Ham radio": { es: "Radioaficionados", fr: "Radioamateurs" },
  "Mystery signals": { es: "Señales misteriosas", fr: "Signaux mystères" },
  Jamming: { es: "Bloqueo de señal", fr: "Brouillage" },
};

const TITLES: Translations = {
  "On the restricted list": { es: "En la lista restringida", fr: "Sur la liste restreinte" },
  "Not on our map": { es: "Fuera de nuestro mapa", fr: "Absent de notre carte" },
  "Something on GPS": { es: "Algo en la banda GPS", fr: "Quelque chose sur le GPS" },
  "Doesn't fit its band": { es: "No encaja en su banda", fr: "Ne correspond pas à sa bande" },
  "Drone that identified itself": { es: "Dron que se identificó", fr: "Drone qui s'est identifié" },
  "Drone with no ID": { es: "Dron sin identificación", fr: "Drone sans identification" },
  "Possible drone": { es: "Posible dron", fr: "Drone possible" },
  "Not usual for this place": { es: "Poco habitual aquí", fr: "Inhabituel ici" },
  "Normal here": { es: "Normal aquí", fr: "Normal ici" },
  "Possible jamming": { es: "Posible bloqueo de señal", fr: "Brouillage possible" },
};

const QUESTIONS: Translations = {
  "Is the signal on GPS dangerous, and what should I check?": {
    es: "¿Es peligrosa la señal en la banda GPS y qué debo revisar?",
    fr: "Le signal sur le GPS est-il dangereux, et que dois-je vérifier ?",
  },
  "What does possible jamming mean, and what should I check?": {
    es: "¿Qué significa un posible bloqueo de señal y qué debo revisar?",
    fr: "Que signifie un brouillage possible, et que dois-je vérifier ?",
  },
  "What should I do about the drone signals?": {
    es: "¿Qué debo hacer con las señales de drones?",
    fr: "Que dois-je faire au sujet des signaux de drones ?",
  },
  "What could the unknown signals be?": {
    es: "¿Qué podrían ser las señales desconocidas?",
    fr: "Que pourraient être les signaux inconnus ?",
  },
  "Explain this report as if I am new to radio.": {
    es: "Explícame este informe como si fuera nuevo en la radio.",
    fr: "Expliquez ce rapport comme si je débutais en radio.",
  },
  "Summarize the classification.": {
    es: "Resume la clasificación.",
    fr: "Résume la classification.",
  },
  "Report anomalies and low-confidence signals.": {
    es: "Informa de las señales inusuales y de las menos seguras.",
    fr: "Signale les signaux inhabituels et les moins sûrs.",
  },
  "Which signal types dominate?": {
    es: "¿Qué tipos de señal predominan?",
    fr: "Quels types de signaux dominent ?",
  },
};
// Built with the site name in pipeline/context.py.
const SITE_QUESTION = /^What is normal at (.+), and why\?$/;

const BADGES: Record<string, MessageKey> = {
  [EN["scan.demoBadge"]]: "scan.demoBadge",
  [EN["scan.andrewBadge"]]: "scan.andrewBadge",
};

export function translate(language: Language, key: MessageKey, vars?: Record<string, string | number>) {
  const text = MESSAGES[language][key] ?? EN[key];
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

function fromTable(table: Translations, text: string, language: Language) {
  if (language === "en") return text;
  return table[text]?.[language] ?? text;
}

/** An everyday category name ("Drones", "Aircraft"), or the English text when unknown. */
export const translateKind = (kind: string, language: Language) => fromTable(KINDS, kind, language);

/** A site-check title ("Possible drone"), or the English text when unknown. */
export const translateTitle = (title: string, language: Language) => fromTable(TITLES, title, language);

/** A suggested question, so a click asks the chat in the chosen language. */
export function translateQuestion(question: string, language: Language) {
  if (language === "en") return question;
  const site = SITE_QUESTION.exec(question)?.[1];
  if (site) {
    return language === "es" ? `¿Qué es normal en ${site} y por qué?` : `Qu'est-ce qui est normal pour ${site}, et pourquoi ?`;
  }
  return fromTable(QUESTIONS, question, language);
}

/** A scene badge from the Laya service; unknown badges are shown as sent. */
export function translateBadge(badge: string, language: Language) {
  const key = BADGES[badge];
  return key ? translate(language, key) : badge;
}

export function isLanguage(value: unknown): value is Language {
  return LANGUAGES.some((entry) => entry.code === value);
}

const STORAGE_KEY = "argus.language";

type LanguageState = {
  language: Language;
  setLanguage: (language: Language) => void;
  /** Read the saved choice; called once in the browser, after the first render. */
  restore: () => void;
};

export const useLanguage = create<LanguageState>((set) => ({
  language: "en",
  setLanguage: (language) => {
    set({ language });
    try {
      window.localStorage.setItem(STORAGE_KEY, language);
    } catch {
      // Private windows and blocked storage: the choice lasts until the page reloads.
    }
  },
  restore: () => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (isLanguage(saved)) set({ language: saved });
    } catch {
      // Storage unavailable: stay on English.
    }
  },
}));

/** The current language and a translator bound to it. */
export function useT() {
  const language = useLanguage((s) => s.language);
  return useMemo(
    () => ({
      language,
      t: (key: MessageKey, vars?: Record<string, string | number>) => translate(language, key, vars),
    }),
    [language],
  );
}
