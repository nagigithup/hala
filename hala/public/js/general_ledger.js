(function () {
	const REPORT_NAME = "General Ledger";
	const ZERO_BALANCE_ROW_CLASS = "hala-gl-zero-balance-row";

	function get_currency_precision(report, data) {
		const balance_column = report.columns?.find(
			(column) => column.fieldname === "balance" || column.id === "balance"
		);
		const precision = Number(frappe.meta.get_field_precision(balance_column, data));
		return Number.isInteger(precision) && precision >= 0 ? precision : 2;
	}

	function is_zero_balance_row(report, data, props) {
		if (props.isHeader || props.isFilter || props.isTotalRow || !data?.posting_date) return false;

		const balance = Number(data.balance);
		if (!Number.isFinite(balance)) return false;

		const precision = get_currency_precision(report, data);
		const half_precision_unit = 0.5 * 10 ** -precision;
		return Math.abs(balance) < half_precision_unit;
	}

	function add_row_class(html) {
		return html.replace('class="dt-row ', `class="dt-row ${ZERO_BALANCE_ROW_CLASS} `);
	}

	function install_row_highlighter(report, datatable) {
		const rowmanager = datatable?.rowmanager;
		if (!rowmanager || rowmanager.hala_zero_balance_highlighter) return;

		rowmanager.hala_zero_balance_highlighter = true;
		const original_get_row_html = rowmanager.getRowHTML.bind(rowmanager);
		rowmanager.getRowHTML = function (row, props) {
			const html = original_get_row_html(row, props);
			const data = datatable.datamanager.getData(props.rowIndex);
			return is_zero_balance_row(report, data, props) ? add_row_class(html) : html;
		};

		// The first render happened before the row renderer was extended.
		datatable.renderBody();
	}

	function enhance_general_ledger(settings, report) {
		if (settings.hala_zero_balance_highlight) return;
		settings.hala_zero_balance_highlight = true;

		const original_after_datatable_render = settings.after_datatable_render;
		settings.after_datatable_render = function (datatable) {
			original_after_datatable_render?.apply(this, arguments);
			install_row_highlighter(report, datatable);
		};
	}

	const original_get_report_settings = frappe.views.QueryReport.prototype.get_report_settings;
	frappe.views.QueryReport.prototype.get_report_settings = function () {
		return original_get_report_settings.apply(this, arguments).then((result) => {
			if (this.report_name === REPORT_NAME) {
				enhance_general_ledger(this.report_settings, this);
			}
			return result;
		});
	};
})();
