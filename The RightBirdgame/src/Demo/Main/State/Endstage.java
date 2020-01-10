package Demo.Main.State;

import Demo.Main.Resources;

import java.awt.*;

/**
 * Created by jassiboy on 2/27/2017.
 */
public class Endstage extends State {
    @Override
    public void update() {

    }

    @Override
    public void render(Graphics g) {
        g.drawImage(Resources.EndstageImage, 0, 0, null);


    }

    @Override
    public void onKeyPressed(int pressedKeyCode) {

    }
}
