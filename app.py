function doGet(e) {
  return handle_(e);
}

function doPost(e) {
  return handle_(e);
}

function handle_(e) {
  try {
    const token = getToken_();

    // ---- read token/action/name from query or JSON body ----
    const query = (e && e.parameter) ? e.parameter : {};
    let body = {};
    if (e && e.postData && e.postData.contents) {
      try { body = JSON.parse(e.postData.contents); } catch (_) { body = {}; }
    }

    const reqToken = (query.token || body.token || "").toString().trim();
    const action = (query.action || body.action || "").toString().trim();
    const name = (query.name || body.name || "").toString().trim();

    if (!token || reqToken !== token) {
      return json_({ ok: false, error: "Unauthorized" }, 401);
    }
    if (!action) {
      return json_({ ok: false, error: "Missing action" }, 400);
    }

    // ---- ensure sheets ----
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const boxSh = ensureSheet_(ss, "box_templates");
    const prodSh = ensureSheet_(ss, "product_templates");

    // ---- ping ----
    if (action === "ping") {
      return json_({ ok: true, message: "pong" }, 200);
    }

    // ---- list templates ----
    if (action === "list_box_templates") {
      const names = listNames_(boxSh).filter(n => n !== "__CURRENT__");
      return json_({ ok: true, names }, 200);
    }
    if (action === "list_product_templates") {
      const names = listNames_(prodSh).filter(n => n !== "__CURRENT__");
      return json_({ ok: true, names }, 200);
    }

    // ---- load template ----
    if (action === "load_box_template") {
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      const payload = getPayload_(boxSh, name);
      if (payload === null) return json_({ ok: false, error: "Not found" }, 404);
      // payload is JSON string -> parse for Streamlit
      return json_({ ok: true, data: safeParse_(payload, []) }, 200);
    }
    if (action === "load_product_template") {
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      const payload = getPayload_(prodSh, name);
      if (payload === null) return json_({ ok: false, error: "Not found" }, 404);
      return json_({ ok: true, data: safeParse_(payload, []) }, 200);
    }

    // ---- save template ----
    if (action === "save_box_template") {
      const data = body.data;
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      if (typeof data === "undefined") return json_({ ok: false, error: "Missing data" }, 400);
      upsert_(boxSh, name, JSON.stringify(data));
      return json_({ ok: true }, 200);
    }
    if (action === "save_product_template") {
      const data = body.data;
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      if (typeof data === "undefined") return json_({ ok: false, error: "Missing data" }, 400);
      upsert_(prodSh, name, JSON.stringify(data));
      return json_({ ok: true }, 200);
    }

    // ---- delete template ----
    if (action === "delete_box_template") {
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      const ok = deleteByName_(boxSh, name);
      return ok ? json_({ ok: true }, 200) : json_({ ok: false, error: "Not found" }, 404);
    }
    if (action === "delete_product_template") {
      if (!name) return json_({ ok: false, error: "Missing name" }, 400);
      const ok = deleteByName_(prodSh, name);
      return ok ? json_({ ok: true }, 200) : json_({ ok: false, error: "Not found" }, 404);
    }

    return json_({ ok: false, error: "Unknown action: " + action }, 400);

  } catch (err) {
    return json_({ ok: false, error: String(err && err.stack ? err.stack : err) }, 500);
  }
}

/* -----------------------
 * Sheet helpers
 * ---------------------- */

function ensureSheet_(ss, sheetName) {
  let sh = ss.getSheetByName(sheetName);
  if (!sh) {
    sh = ss.insertSheet(sheetName);
    sh.getRange(1, 1, 1, 3).setValues([["name", "payload_json", "updated_at"]]);
    sh.setFrozenRows(1);
    sh.autoResizeColumns(1, 3);
  } else {
    // ensure header exists
    const header = sh.getRange(1, 1, 1, Math.max(3, sh.getLastColumn())).getValues()[0];
    const need = ["name", "payload_json", "updated_at"];
    const headerStr = header.map(x => String(x).trim());
    const ok = need.every(k => headerStr.indexOf(k) >= 0);
    if (!ok) {
      sh.clear();
      sh.getRange(1, 1, 1, 3).setValues([["name", "payload_json", "updated_at"]]);
      sh.setFrozenRows(1);
      sh.autoResizeColumns(1, 3);
    }
  }
  return sh;
}

function listNames_(sh) {
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  const values = sh.getRange(2, 1, lastRow - 1, 1).getValues(); // name col
  const out = [];
  for (let i = 0; i < values.length; i++) {
    const n = String(values[i][0] || "").trim();
    if (n) out.push(n);
  }
  // unique
  return Array.from(new Set(out));
}

function getPayload_(sh, name) {
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return null;

  const data = sh.getRange(2, 1, lastRow - 1, 3).getValues(); // name,payload,updated_at
  for (let i = 0; i < data.length; i++) {
    const n = String(data[i][0] || "").trim();
    if (n === name) {
      return String(data[i][1] || "");
    }
  }
  return null;
}

function upsert_(sh, name, payloadJson) {
  const lastRow = sh.getLastRow();
  const now = new Date();

  if (lastRow < 2) {
    sh.appendRow([name, payloadJson, now]);
    return;
  }

  const data = sh.getRange(2, 1, lastRow - 1, 3).getValues();
  for (let i = 0; i < data.length; i++) {
    const n = String(data[i][0] || "").trim();
    if (n === name) {
      const rowIdx = i + 2;
      sh.getRange(rowIdx, 2).setValue(payloadJson);
      sh.getRange(rowIdx, 3).setValue(now);
      return;
    }
  }

  sh.appendRow([name, payloadJson, now]);
}

function deleteByName_(sh, name) {
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return false;

  const data = sh.getRange(2, 1, lastRow - 1, 1).getValues();
  for (let i = 0; i < data.length; i++) {
    const n = String(data[i][0] || "").trim();
    if (n === name) {
      sh.deleteRow(i + 2);
      return true;
    }
  }
  return false;
}

function safeParse_(s, fallback) {
  try {
    const v = JSON.parse(s);
    return v;
  } catch (_) {
    return fallback;
  }
}

/* -----------------------
 * Response helper
 * ---------------------- */
function json_(obj, statusCode) {
  // Apps Script Web App 無法真正設定 HTTP status code，但我們回傳 _status 供前端除錯
  obj = obj || {};
  obj._status = statusCode || 200;
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/* -----------------------
 * Token (Script Properties)
 * ---------------------- */
function getToken_() {
  const props = PropertiesService.getScriptProperties();
  return props.getProperty("TOKEN") || "";
}
