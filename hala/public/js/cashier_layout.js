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
	];

	function navigation_item(item, active) {
		const current = item.id === active;
		return `
			<a class="hala-cashier-nav-item${current ? " is-active" : ""}"
				href="${item.href}" data-hala-nav="${item.id}"
				${current ? 'aria-current="page"' : ""}>
				<span class="hala-cashier-nav-icon">${frappe.utils.icon(item.icon, "md")}</span>
				<span>${item.label}</span>
			</a>
		`;
	}

	function mount({page, active, page_class, content}) {
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
						${navigation.map((item) => navigation_item(item, active)).join("")}
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
			if (!item || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

			event.preventDefault();
			frappe.set_route(...item.route);
		});

		return $layout.find(".hala-cashier-page-shell");
	}

	window.halaCashierLayout = {mount};
})();
