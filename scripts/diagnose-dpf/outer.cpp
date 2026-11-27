#include <dfm-framework/event/event.h>
#include <QDebug>
#include <QObject>
#include <QPluginLoader>
#include <cstdio>

class OuterPlugin : public QObject
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.fedoradde.dpf-probe.outer")
public:
    Q_INVOKABLE int run(QString innerPath)
    {
        // Initialize the packaged framework in the outer plugin's local loader
        // scope before loading a second plugin, as the desktop host does.
        auto *event = dpf::Event::instance();
        event->registerEventType(dpf::EventStratege::kSlot,
                                 "dpf_probe_outer", "slot_Number");
        std::fprintf(stdout, "outer registry=%d converted=%d callback=%d callback_address=%p\n",
                     event->eventType("dpf_probe_outer", "slot_Number"),
                     dpf::EventConverter::convert("dpf_probe_outer", "slot_Number"),
                     int(bool(dpf::EventConverter::convertFunc)),
                     static_cast<const void *>(&dpf::EventConverter::convertFunc));
        std::fflush(stdout);
        QPluginLoader loader(innerPath);
        std::fprintf(stdout, "inner load hints=%d\n", int(loader.loadHints()));
        std::fflush(stdout);
        QObject *inner = loader.instance();
        if (!inner) {
            std::fprintf(stderr, "inner load failed: %s\n", loader.errorString().toUtf8().constData());
            return 5;
        }
        int result = 6;
        if (!QMetaObject::invokeMethod(inner, "run", Qt::DirectConnection,
                                      Q_RETURN_ARG(int, result))) {
            std::fputs("inner run invocation failed\n", stderr);
            return 6;
        }
        return result;
    }
};

#include "outer.moc"
