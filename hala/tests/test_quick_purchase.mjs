import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

let options, config, jobs = 0, silent = true, offline = false, uncertain = false;
const window = {halaSmartPrint(doctype,name,format,settings) {
	assert.equal(doctype,"Purchase Invoice");assert.equal(name,"PINV-TEST");assert.equal(format,"Configured A4");options=settings;
}};
const qz = {
	security: {setCertificatePromise() {},setSignatureAlgorithm() {},setSignaturePromise() {}},
	websocket: {isActive: () => false,async connect(){if(offline)throw Error("QZ unavailable");}},
	printers: {async find(){return ["Office A4"];},async getDefault(){return "Office A4";}},
	configs: {create(printer, settings){assert.equal(printer,"Office A4");config=settings;return settings;}},
	async print(_config,data){jobs++;assert.equal(data[0].format,"pdf");if(uncertain)throw Error("Dispatch uncertain");},
};
const context=vm.createContext({window,qz,console,
	frappe:{call:async()=>({message:{silent_print:Number(silent)}})},
	localStorage:{getItem:()=>null},URLSearchParams,Uint8Array,String,
	btoa: value=>Buffer.from(value,"binary").toString("base64"),
	fetch:async url=>{
		assert.match(url,/doctype=Purchase\+Invoice/);assert.match(url,/format=Configured\+A4/);
		assert.match(url,/no_letterhead=0/);assert.match(url,/_lang=ar/);
		return {ok:true,headers:{get:()=>"application/pdf"},arrayBuffer:async()=>new Uint8Array([37,80,68,70]).buffer};
	},
});
vm.runInContext(readFileSync(new URL("../public/js/booking_pos_print.bundle.js",import.meta.url),"utf8").replace(/^import .*;\n/gm,""),context);
window.halaNativePurchasePrint("PINV-TEST","Configured A4",{letterhead:"Company Letterhead"});
assert.equal(options.paperWidth,undefined);
assert.equal(options.letterhead,"Company Letterhead");
silent=false;assert.equal(await options.beforePrint(),false);assert.equal(jobs,0);
silent=true;offline=true;assert.equal(await options.beforePrint(),false);assert.equal(jobs,0);
offline=false;assert.equal(await options.beforePrint(),true);assert.equal(jobs,1);
assert.equal(config.size,undefined);assert.equal(config.scaleContent,undefined); // Preserve native PDF/printer page configuration.
uncertain=true;await assert.rejects(options.beforePrint(),/Dispatch uncertain/);assert.equal(jobs,2);
console.log("PASS: configured native Purchase Invoice PDF, letterhead and paper preserved; QZ prep fallback; no duplicate browser job after dispatch failure.");
