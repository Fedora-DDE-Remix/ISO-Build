#include <QCoreApplication>
#include <QDebug>
#include <QPluginLoader>
#include <cstdio>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    std::fprintf(stdout, "host argc=%d qt=%s\n", argc, qVersion());
    std::fflush(stdout);
    if (app.arguments().size() != 3) return 2;
    QPluginLoader loader(app.arguments().at(1));
    QObject *plugin = loader.instance();
    if (!plugin) {
        std::fprintf(stderr, "outer load failed: %s\n", loader.errorString().toUtf8().constData());
        return 3;
    }
    int result = 4;
    if (!QMetaObject::invokeMethod(plugin, "run", Qt::DirectConnection,
                                  Q_RETURN_ARG(int, result),
                                  Q_ARG(QString, app.arguments().at(2)))) {
        std::fputs("outer run invocation failed\n", stderr);
        return 4;
    }
    std::fprintf(stdout, "host result=%d\n", result);
    std::fflush(stdout);
    return result;
}
