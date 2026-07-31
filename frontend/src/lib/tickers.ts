/** Static ticker list for search autocomplete — just symbols, not company
 * data, so there's nothing here that can be factually wrong. Any symbol
 * can still be searched directly (Enter navigates regardless of whether
 * it's in this list); this only powers suggestions.
 *
 * TODO(backend): replace with a real symbol-search/autocomplete endpoint
 * once one exists — this list is necessarily incomplete and unmaintained.
 */
export const KNOWN_TICKERS = [
  "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "AVGO",
  "JPM", "V", "MA", "UNH", "HD", "PG", "XOM", "COST", "JNJ", "ORCL",
  "BAC", "KO", "PEP", "ADBE", "CRM", "NFLX", "AMD", "TMO", "ABBV", "CSCO",
  "MCD", "DIS", "WMT", "ABT", "ACN", "LIN", "PFE", "INTC", "IBM", "GE",
  "CAT", "TXN", "VZ", "CMCSA", "NKE", "PM", "UNP", "HON", "RTX", "LOW",
  "AMGN", "SBUX", "BA", "SPGI", "GS", "MS", "BLK", "PLD", "T", "UPS",
  "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",
] as const;
