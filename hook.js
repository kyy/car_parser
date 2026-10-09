// Ждём загрузки библиотеки
function waitForModule(name, callback) {
    var m = Process.findModuleByName(name);
    if (m) { callback(m); return; }
    var iv = setInterval(function() {
        var m = Process.findModuleByName(name);
        if (m) { clearInterval(iv); callback(m); }
    }, 100);
}

waitForModule("libcourage_gate.so", function(mod) {
    var base = mod.base;
    console.log("[+] libcourage_gate.so loaded at " + base);

    // === FUN_001024e4 — сборка соли ===
    Interceptor.attach(base.add(0x24e4), {
        onEnter: function(args) {
            console.log("\n=== FUN_001024e4 ===");
            try {
                console.log("x0 (input str): " + args[0].readUtf8String());
            } catch(e) { console.log("x0 read err: " + e); }
            console.log("x1 (len): " + args[1].toInt32());
            console.log("x2 (out buf): " + args[2]);
        },
        onLeave: function(retval) {
            console.log("retval: " + retval);
        }
    });

    // === FUN_001020e0 — HMAC ===
    Interceptor.attach(base.add(0x20e0), {
        onEnter: function(args) {
            console.log("\n=== FUN_001020e0 (HMAC) ===");
            console.log("x0 (key ptr): " + args[0]);
            try {
                console.log("key hex: " + hexdump(args[0], {length: 32, header: false}));
            } catch(e) { console.log("key read err: " + e); }
            console.log("x1 (key len): " + args[1].toInt32());
            console.log("x2 (data ptr): " + args[2]);
            try {
                console.log("data str: " + args[2].readUtf8String());
            } catch(e) { console.log("data read err: " + e); }
            console.log("x3 (data len): " + args[3].toInt32());
            console.log("x4 (out buf): " + args[4]);
        },
        onLeave: function(retval) {
            console.log("retval: " + retval);
        }
    });

    // === FUN_00101bc0 — SHA256 ===
    Interceptor.attach(base.add(0x1bc0), {
        onEnter: function(args) {
            console.log("\n=== FUN_00101bc0 (SHA256) ===");
            console.log("x0 (data ptr): " + args[0]);
            try {
                console.log("data str: " + args[0].readUtf8String());
            } catch(e) { console.log("data read err: " + e); }
            console.log("x1 (len): " + args[1].toInt32());
            console.log("x2 (out buf): " + args[2]);
        },
        onLeave: function(retval) {
            console.log("retval: " + retval);
        }
    });

    // === nativeMachineCode ===
    Interceptor.attach(base.add(0x2b9c), {
        onEnter: function(args) {
            console.log("\n=== nativeMachineCode ===");
            console.log("jniEnv: " + args[0]);
            console.log("jclass: " + args[1]);
            console.log("jstring: " + args[2]);
        },
        onLeave: function(retval) {
            console.log("retval: " + retval);
        }
    });

    console.log("[+] hooks installed");
});