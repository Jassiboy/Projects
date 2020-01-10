package Demo.Main.State;

import java.awt.*;

/**
 * Created by jassiboy on 2/26/2017.
 */abstract public class State {

    abstract public void update();
    abstract public void render(Graphics g);
    abstract public void onKeyPressed(int pressedKeyCode);
}