(() => {
  "use strict";

  const root = document.getElementById("hala-app");
  if (!root) return;

  const state = {
    boot: null,
    language: localStorage.getItem("hala-language") || (window.halaPageBoot?.language?.startsWith("ar") ? "ar" : "en"),
    theme: localStorage.getItem("hala-theme") || "light",
    company: localStorage.getItem("hala-company") || "",
    page: 1,
    sortBy: "modified",
    sortOrder: "desc",
  };

  const words = {
    en: {business_portal:"Business portal",live_erp:"Live ERPNext data",search_everything:"Search documents…",logout:"Log out",loading:"Loading…",dashboard:"Dashboard",items:"Items & Products",customers:"Customers",suppliers:"Suppliers",purchasing:"Purchasing",sales:"Sales",manufacturing:"BOM & Manufacturing",stock:"Stock",payments:"Payments",journal:"Journal Entries",overview:"Overview",welcome:"Good to see you",operational_summary:"Here is your live business summary.",active_items:"Active items",sales_today:"Sales today",purchases_today:"Purchases today",received_today:"Received today",paid_today:"Paid today",low_stock:"Low stock",drafts:"Drafts requiring attention",quick_actions:"Quick actions",recent:"Recent transactions",create:"Create",new:"New",search:"Search",status:"Status",from:"From",to:"To",filter:"Filter",clear:"Clear",no_records:"No records found",previous:"Previous",next:"Next",showing:"Showing",of:"of",open:"Open",edit:"Edit",submit:"Submit",cancel:"Cancel",print:"Print",pdf:"PDF",open_desk:"Open full ERPNext form",save_draft:"Save draft",add_row:"Add row",remove:"Remove",details:"Details",linked_documents:"Linked documents",created:"Created",modified:"Modified",owner:"Owner",language:"العربية",all_companies:"All companies",all_statuses:"All statuses",draft:"Draft",submitted:"Submitted",cancelled:"Cancelled",error:"Something went wrong",saved:"Document saved",confirm_submit:"Submit this document? ERPNext validations and postings will run.",confirm_cancel:"Cancel this document? ERPNext cancellation rules will run.",notifications:"Open assignments",reports:"Reports"},
    ar: {business_portal:"بوابة الأعمال",live_erp:"بيانات ERPNext مباشرة",search_everything:"ابحث في المستندات…",logout:"تسجيل الخروج",loading:"جارٍ التحميل…",dashboard:"لوحة التحكم",items:"الأصناف والمنتجات",customers:"العملاء",suppliers:"الموردون",purchasing:"المشتريات",sales:"المبيعات",manufacturing:"قوائم المواد والتصنيع",stock:"المخزون",payments:"سندات القبض والصرف",journal:"قيود اليومية",overview:"نظرة عامة",welcome:"مرحباً بك",operational_summary:"هذا هو ملخص أعمالك المباشر.",active_items:"الأصناف النشطة",sales_today:"مبيعات اليوم",purchases_today:"مشتريات اليوم",received_today:"المقبوض اليوم",paid_today:"المدفوع اليوم",low_stock:"مخزون منخفض",drafts:"مسودات تحتاج المتابعة",quick_actions:"إجراءات سريعة",recent:"أحدث المعاملات",create:"إنشاء",new:"جديد",search:"بحث",status:"الحالة",from:"من",to:"إلى",filter:"تصفية",clear:"مسح",no_records:"لا توجد سجلات",previous:"السابق",next:"التالي",showing:"عرض",of:"من",open:"فتح",edit:"تعديل",submit:"اعتماد",cancel:"إلغاء",print:"طباعة",pdf:"PDF",open_desk:"فتح نموذج ERPNext الكامل",save_draft:"حفظ المسودة",add_row:"إضافة صف",remove:"حذف",details:"التفاصيل",linked_documents:"المستندات المرتبطة",created:"الإنشاء",modified:"التعديل",owner:"المالك",language:"English",all_companies:"كل الشركات",all_statuses:"كل الحالات",draft:"مسودة",submitted:"معتمد",cancelled:"ملغى",error:"حدث خطأ",saved:"تم حفظ المستند",confirm_submit:"هل تريد اعتماد المستند؟ ستعمل كل تحققات وترحيلات ERPNext.",confirm_cancel:"هل تريد إلغاء المستند؟ ستعمل قواعد الإلغاء في ERPNext.",notifications:"المهام المفتوحة",reports:"التقارير"}
  };

  const nav = [
    {key:"overview", icon:"⌂", items:[{label:"dashboard", route:"/dashboard"}]},
    {key:"items", icon:"◇", items:[{label:"Items",dt:"Item"},{label:"Item Groups",dt:"Item Group"},{label:"UOMs",dt:"UOM"},{label:"Item Prices",dt:"Item Price"},{label:"Price Lists",dt:"Price List"},{label:"Stock Balance",report:"Stock Balance"}]},
    {key:"customers", icon:"♙", items:[{label:"Customers",dt:"Customer"},{label:"Customer Groups",dt:"Customer Group"},{label:"Customer Ledger",report:"General Ledger"},{label:"Customer Outstanding",report:"Accounts Receivable"}]},
    {key:"suppliers", icon:"♟", items:[{label:"Suppliers",dt:"Supplier"},{label:"Supplier Groups",dt:"Supplier Group"},{label:"Supplier Ledger",report:"General Ledger"},{label:"Supplier Outstanding",report:"Accounts Payable"}]},
    {key:"purchasing", icon:"↓", items:[{label:"Material Requests",dt:"Material Request"},{label:"Requests for Quotation",dt:"Request for Quotation"},{label:"Supplier Quotations",dt:"Supplier Quotation"},{label:"Purchase Orders",dt:"Purchase Order"},{label:"Purchase Receipts",dt:"Purchase Receipt"},{label:"Purchase Invoices",dt:"Purchase Invoice"}]},
    {key:"sales", icon:"↑", items:[{label:"Sales Orders",dt:"Sales Order"},{label:"Delivery Notes",dt:"Delivery Note"},{label:"Sales Invoices",dt:"Sales Invoice"}]},
    {key:"manufacturing", icon:"⚙", items:[{label:"BOMs",dt:"BOM"}]},
    {key:"stock", icon:"▦", items:[{label:"Stock Entries",dt:"Stock Entry"},{label:"Stock Reconciliation",dt:"Stock Reconciliation"},{label:"Warehouses",dt:"Warehouse"},{label:"Stock Balance",report:"Stock Balance"},{label:"Stock Ledger",report:"Stock Ledger"}]},
    {key:"payments", icon:"¤", items:[{label:"Payment Entries",dt:"Payment Entry"},{label:"Payment Summary",report:"Payment Ledger"}]},
    {key:"journal", icon:"≡", items:[{label:"Journal Entries",dt:"Journal Entry"}]},
  ];

  const quick = ["Item","Customer","Supplier","Purchase Order","Purchase Invoice","Sales Invoice","Stock Entry","Payment Entry","Journal Entry"];
  const el = id => document.getElementById(id);
  const t = key => words[state.language][key] || key;
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const debounce = (fn, wait=300) => { let timer; return (...args) => { clearTimeout(timer); timer=setTimeout(()=>fn(...args),wait); }; };
  const formatLabel = key => String(key).replaceAll("_"," ").replace(/\b\w/g, c => c.toUpperCase());
  const routeFor = (kind, doctype, name="") => `/hala/${kind}/${encodeURIComponent(doctype)}${name ? "/"+encodeURIComponent(name) : ""}`;

  async function api(method, args={}, post=false) {
    const url = new URL(`/api/method/hala.api.portal.${method}`, location.origin);
    const options = {credentials:"same-origin", headers:{"Accept":"application/json"}};
    if (post) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.headers["X-Frappe-CSRF-Token"] = root.dataset.csrfToken;
      options.body = JSON.stringify(args);
    } else {
      Object.entries(args).forEach(([key,value]) => value !== undefined && value !== null && value !== "" && url.searchParams.set(key, typeof value === "object" ? JSON.stringify(value) : value));
    }
    const response = await fetch(url, options);
    const payload = await response.json().catch(()=>({}));
    if (!response.ok || payload.exc_type) {
      let message = payload.message || payload.exception || t("error");
      try { const messages=JSON.parse(payload._server_messages||"[]"); if(messages.length) message=messages.map(x=>JSON.parse(x).message).join("\n"); } catch (_) {}
      throw new Error(message.replace(/<[^>]+>/g,""));
    }
    return payload.message;
  }

  function setLoading(show) { el("hala-loader").hidden=!show; }
  function toast(message) { const node=el("hala-toast"); node.textContent=message; node.hidden=false; setTimeout(()=>node.hidden=true,3500); }
  function fail(error, container=el("hala-content")) { console.error(error); container.innerHTML=`<div class="panel empty"><div class="empty-icon">!</div><h2>${escapeHtml(t("error"))}</h2><p>${escapeHtml(error.message||error)}</p></div>`; }
  function money(value) { const company=state.boot?.companies?.find(x=>x.name===state.company); return new Intl.NumberFormat(state.language==="ar"?"ar-SA":"en",{style:"currency",currency:company?.default_currency||"SAR",maximumFractionDigits:2}).format(Number(value||0)); }
  function valueView(value,key="") { if(value===null||value===undefined||value==="") return "—"; if(["grand_total","outstanding_amount","paid_amount","received_amount","total_cost","total_debit","total_credit","difference_amount"].includes(key)) return money(value); if(typeof value==="object") return escapeHtml(JSON.stringify(value)); return escapeHtml(value); }

  function navigate(path, replace=false) {
    history[replace?"replaceState":"pushState"]({},"",path);
    renderRoute();
    closeSidebar();
  }

  function applyLocale() {
    document.documentElement.lang=state.language;
    document.documentElement.dir=state.language==="ar"?"rtl":"ltr";
    document.documentElement.dataset.theme=state.theme;
    document.querySelectorAll("[data-i18n]").forEach(node=>node.textContent=t(node.dataset.i18n));
    document.querySelectorAll("[data-i18n-placeholder]").forEach(node=>node.placeholder=t(node.dataset.i18nPlaceholder));
    el("language-toggle").textContent=t("language");
    renderNav();
  }

  function renderNav() {
    const permissions=state.boot?.permissions||{};
    el("hala-nav").innerHTML=nav.map(group=>{
      const items=group.items.filter(item=>item.report || permissions[item.dt]?.read).map(item=>{
        if(item.report) return `<a class="nav-link" href="/app/query-report/${encodeURIComponent(item.report)}" target="_blank"><span class="nav-icon">↗</span><span>${escapeHtml(item.label)}</span></a>`;
        const path=routeFor("list",item.dt);
        return `<button class="nav-link" data-route="${path}"><span class="nav-icon">·</span><span>${escapeHtml(item.label)}</span></button>`;
      }).join("");
      if(group.key==="overview") return `<button class="nav-link" data-route="/hala/dashboard"><span class="nav-icon">${group.icon}</span><span>${t("dashboard")}</span></button>`;
      const groupLabel=["purchasing","sales"].includes(group.key)?`<button class="nav-link" data-route="/hala/module/${group.key}"><span class="nav-icon">${group.icon}</span><strong>${t(group.key)}</strong></button>`:`<span class="nav-group-label">${t(group.key)}</span>`;
      return items ? `<div class="nav-group">${groupLabel}${items}</div>` : "";
    }).join("");
    el("hala-nav").querySelectorAll("[data-route]").forEach(button=>button.onclick=()=>navigate(button.dataset.route));
  }

  async function renderDashboard() {
    const content=el("hala-content"); setLoading(true);
    try {
      const data=await api("dashboard",{company:state.company});
      const metrics=[
        ["◇","active_items",data.metrics.active_items,false],["♙","customers",data.metrics.customers,false],["♟","suppliers",data.metrics.suppliers,false],["↑","sales_today",data.metrics.sales_today,true],
        ["↓","purchases_today",data.metrics.purchases_today,true],["+","received_today",data.metrics.received_today,true],["−","paid_today",data.metrics.paid_today,true],["!","low_stock",data.metrics.low_stock,false],["…","drafts",data.metrics.drafts,false]
      ];
      content.innerHTML=`<div class="page-head"><div><span class="eyebrow">${t("overview")}</span><h1>${t("welcome")}, ${escapeHtml(state.boot.user.full_name)}</h1><p>${t("operational_summary")}</p></div></div>
        <section class="metrics">${metrics.map(([icon,label,value,currency])=>`<article class="metric-card"><div class="metric-icon">${icon}</div><span>${t(label)}</span><strong>${currency?money(value):Number(value||0).toLocaleString()}</strong></article>`).join("")}</section>
        <section class="dashboard-grid"><div class="panel"><div class="panel-head"><h2>${t("quick_actions")}</h2></div><div class="quick-actions">${quick.filter(dt=>state.boot.permissions[dt]?.create).map(dt=>`<button class="quick-action" data-new="${escapeHtml(dt)}"><strong>＋ ${t("new")}</strong><br><span>${escapeHtml(dt)}</span></button>`).join("")}</div></div>
        <div class="panel"><div class="panel-head"><h2>${t("recent")}</h2></div><div class="recent-list">${data.recent.length?data.recent.map(row=>`<div class="recent-row" data-open="${routeFor("view",row.doctype,row.name)}"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.doctype)}</small><span>${escapeHtml(row.creation)}</span></div>`).join(""):`<div class="empty">${t("no_records")}</div>`}</div></div></section>`;
      content.querySelectorAll("[data-new]").forEach(x=>x.onclick=()=>navigate(routeFor("new",x.dataset.new)));
      content.querySelectorAll("[data-open]").forEach(x=>x.onclick=()=>navigate(x.dataset.open));
    } catch(error){ fail(error,content); } finally { setLoading(false); }
  }

  async function renderList(doctype) {
    const content=el("hala-content"), cfg=state.boot.doctypes[doctype];
    if(!cfg) return fail(new Error("Unknown document type"),content);
    content.innerHTML=`<div class="page-head"><div><span class="eyebrow">${t(cfg.module)}</span><h1>${escapeHtml(cfg.label)}</h1><p>${escapeHtml(doctype)}</p></div><div class="actions">${state.boot.permissions[doctype]?.create?`<button class="btn btn-primary" id="create-record">＋ ${t("create")}</button>`:""}</div></div>
      <div class="toolbar"><input class="grow" id="list-search" placeholder="${t("search")}"><select id="list-status"><option value="">${t("all_statuses")}</option><option value="0">${t("draft")}</option><option value="1">${t("submitted")}</option><option value="2">${t("cancelled")}</option></select><input type="date" id="date-from" aria-label="${t("from")}"><input type="date" id="date-to" aria-label="${t("to")}"><button class="btn" id="apply-filter">${t("filter")}</button></div><div id="list-result"></div>`;
    el("create-record") && (el("create-record").onclick=()=>navigate(routeFor("new",doctype)));
    const load=async()=>{
      const target=el("list-result"); target.innerHTML=`<div class="panel empty">${t("loading")}</div>`;
      try {
        const data=await api("list_records",{doctype,page:state.page,page_size:20,search:el("list-search").value,company:state.company,status:el("list-status").value,from_date:el("date-from").value,to_date:el("date-to").value,sort_by:state.sortBy,sort_order:state.sortOrder});
        if(!data.rows.length){target.innerHTML=`<div class="panel empty"><div class="empty-icon">◇</div>${t("no_records")}</div>`;return;}
        target.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr>${data.fields.map(f=>`<th data-sort="${escapeHtml(f)}">${escapeHtml(formatLabel(f))}</th>`).join("")}</tr></thead><tbody>${data.rows.map(row=>`<tr data-name="${escapeHtml(row.name)}">${data.fields.map(f=>`<td>${f==="status"||f==="docstatus"?statusView(row[f],f):valueView(row[f],f)}</td>`).join("")}</tr>`).join("")}</tbody></table></div><div class="pagination"><span>${t("showing")} ${(data.page-1)*data.page_size+1}–${Math.min(data.page*data.page_size,data.total)} ${t("of")} ${data.total}</span><div><button class="btn" id="prev-page" ${data.page<=1?"disabled":""}>${t("previous")}</button> <button class="btn" id="next-page" ${data.page*data.page_size>=data.total?"disabled":""}>${t("next")}</button></div></div>`;
        target.querySelectorAll("tbody tr").forEach(row=>row.onclick=()=>navigate(routeFor("view",doctype,row.dataset.name)));
        target.querySelectorAll("th[data-sort]").forEach(th=>th.onclick=()=>{state.sortOrder=state.sortBy===th.dataset.sort&&state.sortOrder==="asc"?"desc":"asc";state.sortBy=th.dataset.sort;load();});
        el("prev-page") && (el("prev-page").onclick=()=>{state.page--;load();}); el("next-page") && (el("next-page").onclick=()=>{state.page++;load();});
      } catch(error){fail(error,target);}
    };
    el("apply-filter").onclick=()=>{state.page=1;load();}; el("list-search").addEventListener("input",debounce(()=>{state.page=1;load();})); load();
  }

  async function renderModuleDashboard(module) {
    const content=el("hala-content"); setLoading(true);
    try {
      const data=await api("module_dashboard",{module,company:state.company});
      const labels=module==="purchasing"?{draft_documents:"Draft purchase documents",waiting_receipt:"Orders waiting for receipt",waiting_invoice:"Receipts waiting for invoice",unpaid_invoices:"Unpaid purchase invoices",overdue_invoices:"Overdue supplier invoices",period_total:"Purchasing total this month"}:{draft_documents:"Draft sales documents",waiting_delivery:"Orders waiting for delivery",waiting_invoice:"Deliveries waiting for invoice",unpaid_invoices:"Unpaid sales invoices",overdue_invoices:"Overdue customer invoices",period_total:"Sales total this month"};
      const group=nav.find(x=>x.key===module);
      content.innerHTML=`<div class="page-head"><div><span class="eyebrow">${t("overview")}</span><h1>${t(module)}</h1><p>${t("operational_summary")}</p></div></div><section class="metrics">${Object.entries(data).map(([key,value])=>`<article class="metric-card"><div class="metric-icon">${key==="period_total"?"¤":"◇"}</div><span>${escapeHtml(labels[key]||formatLabel(key))}</span><strong>${key==="period_total"?money(value):Number(value||0).toLocaleString()}</strong></article>`).join("")}</section><section class="panel"><div class="panel-head"><h2>${t(module)}</h2></div><div class="quick-actions">${group.items.filter(item=>item.dt&&state.boot.permissions[item.dt]?.read).map(item=>`<button class="quick-action" data-route="${routeFor("list",item.dt)}"><strong>${escapeHtml(item.label)}</strong><br><span>${state.boot.permissions[item.dt]?.create?"＋ "+t("create"):t("open")}</span></button>`).join("")}</div></section>`;
      content.querySelectorAll("[data-route]").forEach(x=>x.onclick=()=>navigate(x.dataset.route));
    } catch(error){fail(error,content);} finally{setLoading(false);}
  }

  function statusView(value,key) {
    const normalized=key==="docstatus"?({0:"Draft",1:"Submitted",2:"Cancelled"}[value]||value):value;
    return `<span class="status ${String(normalized).toLowerCase().replaceAll(" ","-")}">${escapeHtml(normalized||"—")}</span>`;
  }

  async function renderDetail(doctype,name) {
    const content=el("hala-content"); setLoading(true);
    try {
      const data=await api("get_document",{doctype,name}), doc=data.doc, cfg=state.boot.doctypes[doctype];
      const visible=(cfg.fields||[]).filter(f=>!Array.isArray(doc[f])&&f!=="name");
      const tables=Object.entries(doc).filter(([,v])=>Array.isArray(v)&&v.length);
      content.innerHTML=`<div class="page-head"><div><span class="eyebrow">${escapeHtml(doctype)}</span><h1>${escapeHtml(doc.name)}</h1><p>${statusView(doc.docstatus,"docstatus")}</p></div><div class="actions">${data.actions.write?`<button class="btn" id="edit-doc">${t("edit")}</button>`:""}${data.actions.submit?`<button class="btn btn-primary" id="submit-doc">${t("submit")}</button>`:""}${data.actions.cancel?`<button class="btn btn-danger" id="cancel-doc">${t("cancel")}</button>`:""}${data.actions.print?`<a class="btn" target="_blank" href="/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(name)}">${t("print")}</a><a class="btn" target="_blank" href="/api/method/frappe.utils.print_format.download_pdf?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(name)}&format=Standard&no_letterhead=0">${t("pdf")}</a>`:""}<a class="btn" target="_blank" href="/app/${encodeURIComponent(doctype.toLowerCase().replaceAll(" ","-"))}/${encodeURIComponent(name)}">${t("open_desk")}</a></div></div>
      <div class="detail-grid"><div><section class="panel"><h2>${t("details")}</h2><div class="detail-list">${visible.map(f=>`<div class="detail-field"><label>${escapeHtml(formatLabel(f))}</label><div>${f==="status"||f==="docstatus"?statusView(doc[f],f):valueView(doc[f],f)}</div></div>`).join("")}</div></section>${tables.map(([field,rows])=>renderReadTable(field,rows)).join("")}</div>
      <aside><section class="panel"><h2>${t("linked_documents")}</h2><div class="links">${data.links.length?data.links.map(link=>`<div class="link-card" data-link="${routeFor("view",link.doctype,link.name)}"><strong>${escapeHtml(link.name)}</strong><br><small>${escapeHtml(link.doctype)}</small></div>`).join(""):`<div class="empty">${t("no_records")}</div>`}</div></section><section class="panel" style="margin-top:18px"><div class="detail-field"><label>${t("owner")}</label><div>${escapeHtml(doc.owner)}</div></div><div class="detail-field"><label>${t("created")}</label><div>${escapeHtml(doc.creation)}</div></div><div class="detail-field"><label>${t("modified")}</label><div>${escapeHtml(doc.modified)}</div></div></section></aside></div>`;
      el("edit-doc") && (el("edit-doc").onclick=()=>navigate(routeFor("edit",doctype,name)));
      el("submit-doc") && (el("submit-doc").onclick=()=>act(doctype,name,"submit")); el("cancel-doc") && (el("cancel-doc").onclick=()=>act(doctype,name,"cancel"));
      content.querySelectorAll("[data-link]").forEach(x=>x.onclick=()=>navigate(x.dataset.link));
    } catch(error){fail(error,content);} finally{setLoading(false);}
  }

  function renderReadTable(label,rows) {
    const fields=Object.keys(rows[0]||{}).filter(f=>!["doctype","parent","parentfield","parenttype","idx","name","owner","creation","modified","modified_by","docstatus"].includes(f)&&rows.some(r=>r[f]!==null&&r[f]!==""&&r[f]!==0)).slice(0,10);
    return `<section class="panel" style="margin-top:18px"><h2>${escapeHtml(formatLabel(label))}</h2><div class="child-table"><table><thead><tr>${fields.map(f=>`<th>${escapeHtml(formatLabel(f))}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${fields.map(f=>`<td>${valueView(row[f],f)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
  }

  async function act(doctype,name,action) {
    if(!confirm(t(action==="submit"?"confirm_submit":"confirm_cancel"))) return;
    setLoading(true); try { await api("document_action",{doctype,name,action},true); toast(t("saved")); renderDetail(doctype,name); } catch(error){toast(error.message);} finally{setLoading(false);}
  }

  async function renderForm(doctype,name=null) {
    const content=el("hala-content"); setLoading(true);
    try {
      const data=name?await api("get_document",{doctype,name}):await api("new_document",{doctype});
      const doc=data.doc, schema=data.form;
      content.innerHTML=`<div class="page-head"><div><span class="eyebrow">${name?t("edit"):t("new")}</span><h1>${escapeHtml(doctype)}</h1><p>${name?escapeHtml(name):t("save_draft")}</p></div><div class="actions"><a class="btn" target="_blank" href="/app/${encodeURIComponent(doctype.toLowerCase().replaceAll(" ","-"))}${name?"/"+encodeURIComponent(name):"/new-"+encodeURIComponent(doctype.toLowerCase().replaceAll(" ","-"))}">${t("open_desk")}</a><button class="btn btn-primary" id="save-form">${t("save_draft")}</button></div></div><div id="form-errors" class="form-errors" hidden></div><form id="doc-form" class="panel form-grid" novalidate>${schema.fields.map(field=>renderField(field,doc[field.fieldname],doc)).join("")}</form>`;
      content.querySelectorAll("[data-add-row]").forEach(button=>button.onclick=()=>addTableRow(button.dataset.addRow,schema.fields.find(f=>f.fieldname===button.dataset.addRow).children));
      content.querySelectorAll("[data-remove-row]").forEach(button=>button.onclick=()=>button.closest("tr").remove());
      setupLinkInputs(content);
      if(doctype==="Payment Entry") setupPaymentAllocation(schema);
      if(doctype==="Journal Entry") setupJournalTotals();
      if(doctype==="Stock Entry") setupStockPurposeFields();
      el("save-form").onclick=async()=>{
        const errorBox=el("form-errors"); errorBox.hidden=true;
        try { setLoading(true); const payload=collectForm(doc,schema); const saved=await api("save_document",{doc:payload},true); toast(t("saved")); navigate(routeFor("view",doctype,saved.doc.name),true); }
        catch(error){errorBox.textContent=error.message;errorBox.hidden=false;window.scrollTo({top:0,behavior:"smooth"});} finally{setLoading(false);}
      };
    } catch(error){fail(error,content);} finally{setLoading(false);}
  }

  function renderField(field,value,doc) {
    if(field.fieldtype==="Table") return renderEditTable(field,Array.isArray(value)?value:[]);
    const full=["Text","Small Text","Long Text","Text Editor","Code"].includes(field.fieldtype), required=field.reqd?"required":"";
    let input="";
    if(field.fieldtype==="Check") input=`<input type="checkbox" data-fieldname="${field.fieldname}" data-fieldtype="Check" ${Number(value)?"checked":""}>`;
    else if(field.fieldtype==="Select") input=`<select data-fieldname="${field.fieldname}" data-fieldtype="Select" ${required}>${String(field.options||"").split("\n").map(opt=>`<option value="${escapeHtml(opt)}" ${String(value??"")===opt?"selected":""}>${escapeHtml(opt||"—")}</option>`).join("")}</select>`;
    else if(full) input=`<textarea data-fieldname="${field.fieldname}" data-fieldtype="${field.fieldtype}" ${required}>${escapeHtml(value||"")}</textarea>`;
    else { const type=["Date","Datetime","Time"].includes(field.fieldtype)?field.fieldtype.toLowerCase():["Int","Float","Currency","Percent"].includes(field.fieldtype)?"number":"text"; input=`<input type="${type}" data-fieldname="${field.fieldname}" data-fieldtype="${field.fieldtype}" ${field.fieldtype==="Link"?`data-link-doctype="${escapeHtml(field.options)}" autocomplete="off"`:""} value="${escapeHtml(value??"")}" ${required} ${field.read_only?"readonly":""}>`; }
    return `<div class="field ${full?"full":""} ${field.reqd?"required":""}" data-field-wrapper="${field.fieldname}"><label>${escapeHtml(field.label||formatLabel(field.fieldname))}</label>${input}${field.description?`<div class="help">${escapeHtml(field.description)}</div>`:""}</div>`;
  }

  function renderEditTable(field,rows) {
    return `<div class="table-field" data-table="${field.fieldname}"><div class="panel-head"><h2>${escapeHtml(field.label)}</h2><button type="button" class="btn" data-add-row="${field.fieldname}">＋ ${t("add_row")}</button></div><div class="child-table"><table><thead><tr>${field.children.map(ch=>`<th>${escapeHtml(ch.label||formatLabel(ch.fieldname))}</th>`).join("")}<th></th></tr></thead><tbody>${rows.map(row=>editRow(field.fieldname,field.children,row)).join("")}</tbody></table></div></div>`;
  }

  function editRow(table,fields,row={}) {
    return `<tr>${fields.map(field=>`<td>${childInput(table,field,row[field.fieldname])}</td>`).join("")}<td class="row-actions"><button type="button" class="btn btn-danger" data-remove-row>×</button></td></tr>`;
  }

  function childInput(table,field,value) {
    if(field.fieldtype==="Select") return `<select data-child-field="${field.fieldname}" data-fieldtype="Select">${String(field.options||"").split("\n").map(opt=>`<option ${String(value??"")===opt?"selected":""}>${escapeHtml(opt)}</option>`).join("")}</select>`;
    if(field.fieldtype==="Check") return `<input type="checkbox" data-child-field="${field.fieldname}" data-fieldtype="Check" ${Number(value)?"checked":""}>`;
    const type=["Int","Float","Currency","Percent"].includes(field.fieldtype)?"number":["Date","Datetime","Time"].includes(field.fieldtype)?field.fieldtype.toLowerCase():"text";
    return `<input type="${type}" data-child-field="${field.fieldname}" data-fieldtype="${field.fieldtype}" ${field.fieldtype==="Link"?`data-link-doctype="${escapeHtml(field.options)}" autocomplete="off"`:""} value="${escapeHtml(value??"")}">`;
  }

  function addTableRow(table,fields) {
    const tbody=document.querySelector(`[data-table="${CSS.escape(table)}"] tbody`); tbody.insertAdjacentHTML("beforeend",editRow(table,fields)); const row=tbody.lastElementChild; row.querySelector("[data-remove-row]").onclick=()=>row.remove(); setupLinkInputs(row);
  }

  function castValue(input) {
    if(input.dataset.fieldtype==="Check") return input.checked?1:0;
    if(["Int","Float","Currency","Percent"].includes(input.dataset.fieldtype)) return input.value===""?0:Number(input.value);
    return input.value;
  }

  function collectForm(original,schema) {
    const payload={doctype:original.doctype,name:original.name,docstatus:0};
    schema.fields.forEach(field=>{
      if(field.fieldtype==="Table") {
        payload[field.fieldname]=[...document.querySelectorAll(`[data-table="${CSS.escape(field.fieldname)}"] tbody tr`)].map(row=>{
          const item={doctype:field.options}; row.querySelectorAll("[data-child-field]").forEach(input=>item[input.dataset.childField]=castValue(input)); return item;
        }).filter(row=>Object.entries(row).some(([key,value])=>key!=="doctype"&&value!==""&&value!==0));
      } else {
        const input=document.querySelector(`[data-fieldname="${CSS.escape(field.fieldname)}"]`); if(input) payload[field.fieldname]=castValue(input);
      }
    });
    return payload;
  }

  function fieldValue(name) {
    const input=document.querySelector(`[data-fieldname="${CSS.escape(name)}"]`); return input?castValue(input):"";
  }

  function setupPaymentAllocation(schema) {
    const table=document.querySelector('[data-table="references"]'); if(!table)return;
    const button=document.createElement("button"); button.type="button"; button.className="btn"; button.textContent="↻ Fetch outstanding invoices"; table.querySelector(".panel-head").appendChild(button);
    button.onclick=async()=>{
      const paymentType=fieldValue("payment_type"), partyType=fieldValue("party_type"), party=fieldValue("party");
      const partyAccount=paymentType==="Receive"?fieldValue("paid_from"):fieldValue("paid_to");
      if(!partyType||!party||!partyAccount){toast("Select payment type, party and party account first.");return;}
      try {
        setLoading(true);
        const rows=await api("outstanding_invoices",{company:fieldValue("company"),party_type:partyType,party,party_account:partyAccount,payment_type:paymentType,posting_date:fieldValue("posting_date")});
        const fields=schema.fields.find(f=>f.fieldname==="references").children;
        table.querySelector("tbody").innerHTML=rows.map(row=>editRow("references",fields,{reference_doctype:row.voucher_type,reference_name:row.voucher_no,total_amount:row.invoice_amount,outstanding_amount:row.outstanding_amount,allocated_amount:row.outstanding_amount,exchange_rate:row.exchange_rate})).join("");
        table.querySelectorAll("[data-remove-row]").forEach(x=>x.onclick=()=>x.closest("tr").remove()); setupLinkInputs(table);
      } catch(error){toast(error.message);} finally{setLoading(false);}
    };
  }

  function setupJournalTotals() {
    const table=document.querySelector('[data-table="accounts"]'); if(!table)return;
    const summary=document.createElement("div"); summary.className="status"; table.querySelector(".panel-head").appendChild(summary);
    const update=()=>{let debit=0,credit=0;table.querySelectorAll('input[data-child-field="debit_in_account_currency"]').forEach(x=>debit+=Number(x.value||0));table.querySelectorAll('input[data-child-field="credit_in_account_currency"]').forEach(x=>credit+=Number(x.value||0));summary.textContent=`Debit: ${money(debit)} · Credit: ${money(credit)} · Difference: ${money(debit-credit)}`;};
    table.addEventListener("input",update); table.addEventListener("click",()=>setTimeout(update)); update();
  }

  function setupStockPurposeFields() {
    const purpose=document.querySelector('[data-fieldname="stock_entry_type"]')||document.querySelector('[data-fieldname="purpose"]'); if(!purpose)return;
    const update=()=>{const value=purpose.value; const from=document.querySelector('[data-field-wrapper="from_warehouse"]'),to=document.querySelector('[data-field-wrapper="to_warehouse"]'); if(from)from.hidden=value==="Material Receipt"; if(to)to.hidden=value==="Material Issue";};
    purpose.addEventListener("change",update); update();
  }

  function setupLinkInputs(scope) {
    scope.querySelectorAll("input[data-link-doctype]").forEach(input=>{
      const listId=`links-${Math.random().toString(36).slice(2)}`; const list=document.createElement("datalist"); list.id=listId; document.body.appendChild(list); input.setAttribute("list",listId);
      input.addEventListener("input",debounce(async()=>{ if(input.value.length<1)return; try{const rows=await api("link_options",{doctype:input.dataset.linkDoctype,txt:input.value,page_length:15});list.innerHTML=rows.map(r=>`<option value="${escapeHtml(r.name)}"></option>`).join("");}catch(_){list.innerHTML="";} },250));
    });
  }

  function parseRoute() {
    const parts=location.pathname.replace(/^\/hala\/?/,"").split("/").filter(Boolean).map(decodeURIComponent);
    return {kind:parts[0]||"dashboard",doctype:parts[1],name:parts.slice(2).join("/")};
  }
  function renderRoute() {
    state.page=1; const route=parseRoute(); document.querySelectorAll(".nav-link").forEach(x=>x.classList.toggle("active",x.dataset.route===location.pathname));
    if(route.kind==="dashboard") return renderDashboard();
    if(route.kind==="module"&&["purchasing","sales"].includes(route.doctype)) return renderModuleDashboard(route.doctype);
    if(route.kind==="list"&&route.doctype) return renderList(route.doctype);
    if(route.kind==="view"&&route.doctype&&route.name) return renderDetail(route.doctype,route.name);
    if(route.kind==="new"&&route.doctype) return renderForm(route.doctype);
    if(route.kind==="edit"&&route.doctype&&route.name) return renderForm(route.doctype,route.name);
    navigate("/hala/dashboard",true);
  }

  function closeSidebar(){el("hala-sidebar").classList.remove("open");el("hala-overlay").hidden=true;}
  async function init() {
    setLoading(true);
    try {
      state.boot=await api("boot");
      if(!state.company||!state.boot.companies.some(x=>x.name===state.company)) state.company=state.boot.default_company||state.boot.companies[0]?.name||"";
      el("company-selector").innerHTML=`<option value="">${t("all_companies")}</option>`+state.boot.companies.map(c=>`<option value="${escapeHtml(c.name)}" ${c.name===state.company?"selected":""}>${escapeHtml(c.name)}</option>`).join("");
      el("user-name").textContent=state.boot.user.full_name; el("user-avatar").textContent=(state.boot.user.full_name||"H").trim()[0].toUpperCase(); el("notification-count").textContent=state.boot.notifications;
      applyLocale(); renderRoute();
    } catch(error){fail(error);} finally{setLoading(false);}
  }

  el("company-selector").onchange=e=>{state.company=e.target.value;localStorage.setItem("hala-company",state.company);renderRoute();};
  el("theme-toggle").onclick=()=>{state.theme=state.theme==="dark"?"light":"dark";localStorage.setItem("hala-theme",state.theme);document.documentElement.dataset.theme=state.theme;};
  el("user-button").onclick=()=>el("user-popover").hidden=!el("user-popover").hidden;
  el("language-toggle").onclick=()=>{state.language=state.language==="ar"?"en":"ar";localStorage.setItem("hala-language",state.language);applyLocale();renderRoute();};
  el("open-sidebar").onclick=()=>{el("hala-sidebar").classList.add("open");el("hala-overlay").hidden=false;}; el("close-sidebar").onclick=closeSidebar; el("hala-overlay").onclick=closeSidebar;
  el("notification-button").onclick=()=>toast(`${t("notifications")}: ${state.boot?.notifications||0}`);
  el("global-search").addEventListener("input",debounce(async e=>{const box=el("search-results"),value=e.target.value.trim();if(value.length<2){box.hidden=true;return;}try{const rows=await api("global_search",{txt:value});box.innerHTML=rows.length?rows.map(r=>`<button class="search-result" data-route="${routeFor("view",r.doctype,r.name)}"><strong>${escapeHtml(r.name)}</strong><small>${escapeHtml(r.doctype)}</small></button>`).join(""):`<div class="empty">${t("no_records")}</div>`;box.hidden=false;box.querySelectorAll("[data-route]").forEach(x=>x.onclick=()=>{box.hidden=true;navigate(x.dataset.route);});}catch(_){box.hidden=true;}},300));
  window.addEventListener("popstate",renderRoute);
  document.addEventListener("click",e=>{if(!e.target.closest(".user-menu"))el("user-popover").hidden=true;if(!e.target.closest(".global-search"))el("search-results").hidden=true;});
  init();
})();
