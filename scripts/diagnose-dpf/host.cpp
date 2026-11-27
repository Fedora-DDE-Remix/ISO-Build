#include <QCoreApplication>
#include <QDebug>
#include <QPluginLoader>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (app.arguments().size() != 3) return 2;
    QPluginLoader loader(app.arguments().at(1));
    QObject *plugin = loader.instance();
    if (!plugin) { qCritical() << loader.errorString(); return 3; }
    int result = 4;
    if (!QMetaObject::invokeMethod(plugin, "run", Qt::DirectConnection,
                                  Q_RETURN_ARG(int, result),
                                  Q_ARG(QString, app.arguments().at(2)))) return 4;
    return result;
}
