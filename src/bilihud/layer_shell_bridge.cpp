#include <QWindow>
#include <LayerShellQt/Window>

#include <QRegion>
#include <QRect>

#include <QGuiApplication>
#include <qpa/qplatformnativeinterface.h>
#include <wayland-client.h>


extern "C" {
    void make_overlay(void* window_ptr) {
        if (!window_ptr) return;

        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            ls_window->setLayer(LayerShellQt::Window::LayerOverlay);
            // Use -1 for no exclusive zone (fully ignored by tiling layout)
            ls_window->setExclusiveZone(-1);
            ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
            
            // Anchors are required for proper positioning dynamics in some compositors
            ls_window->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorLeft));
            
            ls_window->setScope("bilihud");
        }
    }


    void set_passthrough(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        
        // Get native interface to access Wayland internals
        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;

        // Get wl_surface
        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;

        // Get wl_compositor (usually registred as "compositor" or "wl_compositor" integration)
        // QtWayland typically provides "compositor" or "wl_compositor" resource
        struct wl_compositor* compositor = (struct wl_compositor*)native->nativeResourceForIntegration("compositor");
        
        // Some Qt versions might use different keys, try "wl_compositor" if "compositor" fails
        if (!compositor) {
            compositor = (struct wl_compositor*)native->nativeResourceForIntegration("wl_compositor");
        }

        if (surface && compositor) {
            if (enabled) {
                // Enabled pass-through: Set EMPTY input region
                // This means no input events are accepted by this surface
                struct wl_region* region = wl_compositor_create_region(compositor);
                wl_surface_set_input_region(surface, region);
                wl_region_destroy(region);
            } else {
                // Disabled pass-through: Set NULL input region
                // NULL means the input region is infinite (surface accepts all input)
                wl_surface_set_input_region(surface, nullptr);
            }
            wl_surface_commit(surface);
        }
    }

    void set_anchor_position(void* window_ptr, int x, int y) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);
        
        if (ls_window) {
            // Anchor is Top | Left, so margins define X (Left) and Y (Top)
            QMargins margins;
            margins.setLeft(x);
            margins.setTop(y);
            margins.setRight(0);
            margins.setBottom(0);
            ls_window->setMargins(margins);
        }
    }

    void set_keyboard_interactivity(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);
        
        if (ls_window) {
            if (enabled) {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
            } else {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
            }
        }
    }
}
