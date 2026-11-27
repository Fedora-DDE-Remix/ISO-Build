#include <dfm-framework/event/event.h>
#include <QDebug>
#include <QObject>
#include <QPluginLoader>

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
        qInfo() << "outer registry=" << event->eventType("dpf_probe_outer", "slot_Number")
                << "converted=" << dpf::EventConverter::convert("dpf_probe_outer", "slot_Number")
                << "callback=" << bool(dpf::EventConverter::convertFunc)
                << "callback_address=" << reinterpret_cast<quintptr>(&dpf::EventConverter::convertFunc);
        QPluginLoader loader(innerPath);
        qInfo() << "inner load hints=" << loader.loadHints();
        QObject *inner = loader.instance();
        if (!inner) { qCritical() << loader.errorString(); return 5; }
        int result = 6;
        if (!QMetaObject::invokeMethod(inner, "run", Qt::DirectConnection,
                                      Q_RETURN_ARG(int, result))) return 6;
        return result;
    }
};

#include "outer.moc"
