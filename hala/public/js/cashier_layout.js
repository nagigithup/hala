(function () {
	const navigation = [
		{
			id: "booking",
			label: "فاتورة الحجز",
			icon: "calendar",
			href: "/desk/hala-booking",
			route: ["hala-booking"],
		},
		{
			id: "deposit",
			label: "استلام التأمين",
			icon: "archive",
			href: "/desk/hala-deposit",
			route: ["hala-deposit"],
		},
		{
			id: "receipt",
			label: "سند قبض",
			icon: "file-text",
			href: "/desk/hala-receipt",
			route: ["hala-receipt"],
		},
		{
			id: "disbursement",
			label: "سند صرف",
			icon: "banknote-arrow-up",
			script: "disbursement",
			controller: "HalaDisbursement",
			roles: ["سند الصرف", "System Manager"],
		},
		{
			id: "purchase",
			label: "فاتورة مشتريات",
			icon: "shopping-cart",
			script: "quick_purchase",
			controller: "HalaQuickPurchase",
			roles: ["Purchase Manager", "System Manager"],
		},
		{
			id: "booking-history",
			label: "سجل فواتير الحجز",
			icon: "clock",
			href: "/desk/hala-booking-history",
			route: ["hala-booking-history"],
		},
	];

	const is_visible = (item) => !item.roles || item.roles.some(role => frappe.user?.has_role(role));

	function navigation_item(item, active) {
		const current = item.id === active;
		const tag = item.script ? "button" : "a";
		return `
			<${tag} class="hala-cashier-nav-item${current ? " is-active" : ""}"
				${item.script ? 'type="button"' : `href="${item.href}"`} data-hala-nav="${item.id}"
				${current ? 'aria-current="page"' : ""}>
				<span class="hala-cashier-nav-icon">${frappe.utils.icon(item.icon, "md")}</span>
				<span>${item.label}</span>
			</${tag}>
		`;
	}

	function set_active(page, active) {
		page.main.find("[data-hala-nav]").each((_, element) => {
			const current = element.dataset.halaNav === active;
			$(element).toggleClass("is-active", current).attr("aria-current", current ? "page" : null);
		});
	}

	async function show_action(page, id) {
		const item = navigation.find(item => item.id === id && item.script);
		if (!item || !is_visible(item)) return;
		await frappe.require(`/assets/hala/js/${item.script}.js`);
		const key = `hala_nav_${id}`;
		page[key] = page[key] || new window[item.controller](page);
		await page[key].show();
		set_active(page, id);
		page.main.find(".hala-cashier-sidebar").removeClass("is-open");
		page.main.find(".hala-cashier-menu-toggle").attr("aria-expanded", "false");
		page[key].dialog.$wrapper.off("hidden.bs.modal.hala_nav").one("hidden.bs.modal.hala_nav", () => set_active(page, page.hala_nav_active));
		return page[key];
	}

	function mount({page, active, page_class, content}) {
		page.hala_nav_active = active;
		page.main.addClass("hala-cashier-desk-page");
		page.main.html(`
			<div class="hala-cashier-layout" dir="rtl">
				<aside class="hala-cashier-sidebar" aria-label="التنقل في صفحات هلا">
					<div class="hala-cashier-sidebar-header">
						<div class="hala-cashier-brand">
							<span class="hala-cashier-brand-mark">H</span>
							<span>HALA</span>
						</div>
						<button type="button" class="hala-cashier-menu-toggle"
							aria-label="عرض قائمة هلا" aria-expanded="false">
							${frappe.utils.icon("menu", "md")}
						</button>
					</div>
					<nav class="hala-cashier-nav">
						${navigation.filter(is_visible).map((item) => navigation_item(item, active)).join("")}
					</nav>
				</aside>
				<div class="hala-cashier-content">
					<div class="hala-cashier-page-shell ${page_class || ""}">${content}</div>
				</div>
			</div>
		`);

		const $layout = page.main.find(".hala-cashier-layout");
		const $sidebar = $layout.find(".hala-cashier-sidebar");
		const $toggle = $layout.find(".hala-cashier-menu-toggle");

		$toggle.on("click", () => {
			const open = !$sidebar.hasClass("is-open");
			$sidebar.toggleClass("is-open", open);
			$toggle.attr("aria-expanded", open ? "true" : "false");
		});

		$layout.on("click", "[data-hala-nav]", (event) => {
			const item = navigation.find(({id}) => id === event.currentTarget.dataset.halaNav);
			if (!item || !is_visible(item)) return;
			if (item.script) {
				event.preventDefault();
				return show_action(page, item.id);
			}
			if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

			event.preventDefault();
			frappe.set_route(...item.route);
		});

		return $layout.find(".hala-cashier-page-shell");
	}

	window.halaCashierLayout = {mount, show_action};
})();
