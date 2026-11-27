#include <dfm-framework/event/event.h>
#include <QDebug>
#include <QJsonDocument>
#include <QJsonObject>
#include <QObject>
#include <cstdio>

class ProbeHandler : public QObject
{
    Q_OBJECT
public:
    int number() { return 37; }
    QList<int> numbers() { return { 11, 22 }; }
};

class InnerPlugin : public QObject
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.fedoradde.dpf-probe.inner")
public:
    Q_INVOKABLE int run()
    {
        const QString space = "dpf_probe_inner";
        const QString numberTopic = "slot_Number";
        auto *event = dpf::Event::instance();
        const auto registered = event->eventType(space, numberTopic);
        const auto converted = dpf::EventConverter::convert(space, numberTopic);
        ProbeHandler handler;
        const bool numberConnected = dpfSlotChannel->connect(space, numberTopic, &handler, &ProbeHandler::number);
        const bool listConnected = dpfSlotChannel->connect(space, "slot_Numbers", &handler, &ProbeHandler::numbers);
        const QVariant number = dpfSlotChannel->push(space, numberTopic);
        const QVariant list = dpfSlotChannel->push(space, "slot_Numbers");
        const bool result = registered > 0 && registered == converted
                            && numberConnected && listConnected
                            && number.isValid() && number.toInt() == 37
                            && list.isValid() && list.value<QList<int>>() == QList<int>({11, 22});
        QJsonObject report {
            { "qt_version", qVersion() },
            { "registry_id", registered },
            { "converted_id", converted },
            { "callback_valid", bool(dpf::EventConverter::convertFunc) },
            { "callback_address", QString::number(reinterpret_cast<quintptr>(&dpf::EventConverter::convertFunc), 16) },
            { "number_connected", numberConnected },
            { "list_connected", listConnected },
            { "number_variant_valid", number.isValid() },
            { "number", number.toInt() },
            { "list_variant_valid", list.isValid() },
            { "list_size", list.value<QList<int>>().size() },
            { "passed", result }
        };
        const QByteArray json = QJsonDocument(report).toJson(QJsonDocument::Compact);
        std::fprintf(stdout, "%s\n", json.constData());
        std::fflush(stdout);
        return result ? 0 : 1;
    }
private:
    // These are exactly the same registration macros used by ddplugin_core.
    DPF_EVENT_NAMESPACE(dpf_probe_inner)
    DPF_EVENT_REG_SLOT(slot_Number)
    DPF_EVENT_REG_SLOT(slot_Numbers)
};

#include "inner.moc"
