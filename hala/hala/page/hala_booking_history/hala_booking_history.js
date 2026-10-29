frappe.pages["hala-booking-history"].on_page_load = function (wrapper) {
	wrapper.hala_history_ready = frappe.require("/assets/hala/js/booking_page.js").then(() => {
		wrapper.hala_history = new window.HalaBookingPage(wrapper, {history: true});
	});
};

frappe.pages["hala-booking-history"].on_page_show = async function (wrapper) {
	await wrapper.hala_history_ready;
	return wrapper.hala_history.show();
};
