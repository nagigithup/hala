frappe.pages["hala-booking"].on_page_load = function (wrapper) {
	wrapper.hala_booking_ready = frappe.require("/assets/hala/js/booking_page.js").then(() => {
		wrapper.hala_booking = new window.HalaBookingPage(wrapper);
	});
};

frappe.pages["hala-booking"].on_page_show = async function (wrapper) {
	await wrapper.hala_booking_ready;
	return wrapper.hala_booking.show();
};
